#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/landlock.h>
#include <linux/seccomp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

static int add_path_rule(int ruleset_fd, const char *path, uint64_t access) {
    int fd = open(path, O_PATH | O_CLOEXEC);
    if (fd < 0) {
        if (errno == ENOENT || errno == ENOTDIR) return 0;
        return -1;
    }
    struct landlock_path_beneath_attr rule = {
        .allowed_access = access,
        .parent_fd = fd,
    };
    int result = syscall(__NR_landlock_add_rule, ruleset_fd, LANDLOCK_RULE_PATH_BENEATH, &rule, 0);
    int saved = errno;
    close(fd);
    errno = saved;
    return result;
}

#if defined(__x86_64__)
#define EVAL_AUDIT_ARCH AUDIT_ARCH_X86_64
#elif defined(__aarch64__)
#define EVAL_AUDIT_ARCH AUDIT_ARCH_AARCH64
#else
#error "The evaluation shell sandbox needs an explicit seccomp architecture mapping"
#endif

static int install_network_filter(void) {
#define DENY_SYSCALL(number) \
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (number), 0, 1), \
    BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | (EPERM & SECCOMP_RET_DATA))
    struct sock_filter instructions[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, EVAL_AUDIT_ARCH, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        DENY_SYSCALL(__NR_socket),
        DENY_SYSCALL(__NR_socketpair),
        DENY_SYSCALL(__NR_connect),
        DENY_SYSCALL(__NR_bind),
        DENY_SYSCALL(__NR_listen),
        DENY_SYSCALL(__NR_accept),
        DENY_SYSCALL(__NR_accept4),
        DENY_SYSCALL(__NR_sendto),
        DENY_SYSCALL(__NR_recvfrom),
        DENY_SYSCALL(__NR_sendmsg),
        DENY_SYSCALL(__NR_recvmsg),
        DENY_SYSCALL(__NR_shutdown),
        DENY_SYSCALL(__NR_getsockname),
        DENY_SYSCALL(__NR_getpeername),
        DENY_SYSCALL(__NR_setsockopt),
        DENY_SYSCALL(__NR_getsockopt),
#ifdef __NR_sendmmsg
        DENY_SYSCALL(__NR_sendmmsg),
#endif
#ifdef __NR_recvmmsg
        DENY_SYSCALL(__NR_recvmmsg),
#endif
#ifdef __NR_io_uring_setup
        DENY_SYSCALL(__NR_io_uring_setup),
#endif
#ifdef __NR_io_uring_enter
        DENY_SYSCALL(__NR_io_uring_enter),
#endif
#ifdef __NR_io_uring_register
        DENY_SYSCALL(__NR_io_uring_register),
#endif
#ifdef __NR_socketcall
        DENY_SYSCALL(__NR_socketcall),
#endif
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
#undef DENY_SYSCALL
    struct sock_fprog program = {
        .len = (unsigned short)(sizeof(instructions) / sizeof(instructions[0])),
        .filter = instructions,
    };
    return prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fputs("landlock-shell: expected shell arguments\n", stderr);
        return 64;
    }
    int abi = syscall(__NR_landlock_create_ruleset, NULL, 0, LANDLOCK_CREATE_RULESET_VERSION);
    if (abi < 1) {
        fputs("landlock-shell: required Landlock filesystem isolation is unavailable\n", stderr);
        return 69;
    }

    uint64_t read_execute = LANDLOCK_ACCESS_FS_EXECUTE |
                            LANDLOCK_ACCESS_FS_READ_FILE |
                            LANDLOCK_ACCESS_FS_READ_DIR;
    uint64_t writable = LANDLOCK_ACCESS_FS_WRITE_FILE |
                        LANDLOCK_ACCESS_FS_REMOVE_DIR |
                        LANDLOCK_ACCESS_FS_REMOVE_FILE |
                        LANDLOCK_ACCESS_FS_MAKE_CHAR |
                        LANDLOCK_ACCESS_FS_MAKE_DIR |
                        LANDLOCK_ACCESS_FS_MAKE_REG |
                        LANDLOCK_ACCESS_FS_MAKE_SOCK |
                        LANDLOCK_ACCESS_FS_MAKE_FIFO |
                        LANDLOCK_ACCESS_FS_MAKE_BLOCK |
                        LANDLOCK_ACCESS_FS_MAKE_SYM;
    uint64_t handled = read_execute | writable;
    if (abi >= 2) handled |= LANDLOCK_ACCESS_FS_REFER;
    if (abi >= 3) handled |= LANDLOCK_ACCESS_FS_TRUNCATE;

    struct landlock_ruleset_attr ruleset = {.handled_access_fs = handled};
    int ruleset_fd = syscall(__NR_landlock_create_ruleset, &ruleset, sizeof(ruleset), 0);
    if (ruleset_fd < 0) {
        perror("landlock-shell: create ruleset");
        return 70;
    }

    const char *readonly_paths[] = {"/usr", "/bin", "/lib", "/lib64", "/etc",
                                    "/dev", "/tmp/tools", "/tmp/home/.config/opencode"};
    for (size_t i = 0; i < sizeof(readonly_paths) / sizeof(readonly_paths[0]); i++) {
        if (add_path_rule(ruleset_fd, readonly_paths[i], read_execute) < 0) {
            perror("landlock-shell: add read-only path");
            close(ruleset_fd);
            return 70;
        }
    }

    const char *device_paths[] = {"/dev/null", "/dev/urandom", "/dev/random", "/dev/zero"};
    const uint64_t device_access[] = {LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_WRITE_FILE,
                                      LANDLOCK_ACCESS_FS_READ_FILE, LANDLOCK_ACCESS_FS_READ_FILE,
                                      LANDLOCK_ACCESS_FS_READ_FILE};
    for (size_t i = 0; i < sizeof(device_paths) / sizeof(device_paths[0]); i++) {
        if (add_path_rule(ruleset_fd, device_paths[i], device_access[i]) < 0) {
            perror("landlock-shell: add device path");
            close(ruleset_fd);
            return 70;
        }
    }

    const char *writable_paths[] = {"/tmp/workspace", "/tmp/home/.local/state", "/tmp/home/.cache"};
    for (size_t i = 0; i < sizeof(writable_paths) / sizeof(writable_paths[0]); i++) {
        if (add_path_rule(ruleset_fd, writable_paths[i], handled) < 0) {
            perror("landlock-shell: add writable path");
            close(ruleset_fd);
            return 70;
        }
    }

    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0 || install_network_filter() < 0 ||
        syscall(__NR_landlock_restrict_self, ruleset_fd, 0) < 0) {
        perror("landlock-shell: install shell restrictions");
        close(ruleset_fd);
        return 70;
    }
    close(ruleset_fd);

    argv[0] = "/usr/bin/bash";
    execv(argv[0], argv);
    perror("landlock-shell: exec bash");
    return 71;
}
