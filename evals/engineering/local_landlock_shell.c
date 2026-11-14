#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/landlock.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
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

static int add_path_list(int ruleset_fd, const char *paths, uint64_t access) {
    if (!paths || !*paths) return 0;
    char *copy = strdup(paths);
    if (!copy) return -1;
    char *save = NULL;
    for (char *path = strtok_r(copy, ":", &save); path; path = strtok_r(NULL, ":", &save)) {
        if (!*path || path[0] != '/' || add_path_rule(ruleset_fd, path, access) < 0) {
            free(copy);
            return -1;
        }
    }
    free(copy);
    return 0;
}

#if defined(__x86_64__)
#define EVAL_AUDIT_ARCH AUDIT_ARCH_X86_64
#elif defined(__aarch64__)
#define EVAL_AUDIT_ARCH AUDIT_ARCH_AARCH64
#else
#error "The local evaluation shell needs an explicit seccomp architecture mapping"
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

static int cwd_is_inside(const char *workspace) {
    char cwd[4096];
    if (!getcwd(cwd, sizeof(cwd))) return 0;
    size_t length = strlen(workspace);
    return strncmp(cwd, workspace, length) == 0 && (cwd[length] == '/' || cwd[length] == '\0');
}

static int preserve_env(const char *name, const char *value) {
    return value && *value ? setenv(name, value, 1) : 0;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fputs("local-landlock-shell: expected shell arguments\n", stderr);
        return 64;
    }

    const char *workspace_input = getenv("ANVIL_EVAL_WORKSPACE");
    const char *state_root = getenv("ANVIL_EVAL_STATE_ROOT");
    const char *read_roots = getenv("ANVIL_EVAL_READ_ROOTS");
    const char *home_env = getenv("HOME");
    const char *xdg_config_env = getenv("XDG_CONFIG_HOME");
    const char *xdg_data_env = getenv("XDG_DATA_HOME");
    const char *xdg_state_env = getenv("XDG_STATE_HOME");
    const char *xdg_cache_env = getenv("XDG_CACHE_HOME");
    const char *eval_state_home_env = getenv("ANVIL_EVAL_STATE_HOME");
    char *home = home_env ? strdup(home_env) : NULL;
    char *xdg_config = xdg_config_env ? strdup(xdg_config_env) : NULL;
    char *xdg_data = xdg_data_env ? strdup(xdg_data_env) : NULL;
    char *xdg_state = xdg_state_env ? strdup(xdg_state_env) : NULL;
    char *xdg_cache = xdg_cache_env ? strdup(xdg_cache_env) : NULL;
    char *eval_state_home = eval_state_home_env ? strdup(eval_state_home_env) : NULL;
    char *workspace = workspace_input ? realpath(workspace_input, NULL) : NULL;
    if (eval_state_home_env && !eval_state_home) {
        fputs("local-landlock-shell: could not retain the temporary Anvil state path\n", stderr);
        free(home);
        free(xdg_config);
        free(xdg_data);
        free(xdg_state);
        free(xdg_cache);
        free(workspace);
        return 70;
    }
    if (!workspace || workspace[0] != '/' || !strcmp(workspace, "/") || !cwd_is_inside(workspace)) {
        fputs("local-landlock-shell: invalid or non-current evaluation workspace\n", stderr);
        free(workspace);
        free(home);
        free(xdg_config);
        free(xdg_data);
        free(xdg_state);
        free(xdg_cache);
        return 65;
    }

    int abi = syscall(__NR_landlock_create_ruleset, NULL, 0, LANDLOCK_CREATE_RULESET_VERSION);
    if (abi < 1) {
        fputs("local-landlock-shell: required Landlock filesystem isolation is unavailable\n", stderr);
        free(workspace);
        free(home);
        free(xdg_config);
        free(xdg_data);
        free(xdg_state);
        free(xdg_cache);
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
        perror("local-landlock-shell: create ruleset");
        free(workspace);
        free(home);
        free(xdg_config);
        free(xdg_data);
        free(xdg_state);
        free(xdg_cache);
        return 70;
    }

    const char *readonly_paths[] = {"/usr", "/bin", "/lib", "/lib64", "/dev"};
    for (size_t i = 0; i < sizeof(readonly_paths) / sizeof(readonly_paths[0]); i++) {
        if (add_path_rule(ruleset_fd, readonly_paths[i], read_execute) < 0) {
            perror("local-landlock-shell: add system read path");
            close(ruleset_fd);
            free(workspace);
            free(home);
            free(xdg_config);
            free(xdg_data);
            free(xdg_state);
            free(xdg_cache);
            return 70;
        }
    }
    if (add_path_rule(ruleset_fd, workspace, handled) < 0 ||
        (state_root && *state_root && add_path_rule(ruleset_fd, state_root, handled) < 0) ||
        add_path_list(ruleset_fd, read_roots, read_execute) < 0) {
        perror("local-landlock-shell: add evaluation path");
        close(ruleset_fd);
        free(workspace);
        free(home);
        free(xdg_config);
        free(xdg_data);
        free(xdg_state);
        free(xdg_cache);
        return 70;
    }

    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0 || install_network_filter() < 0 ||
        syscall(__NR_landlock_restrict_self, ruleset_fd, 0) < 0) {
        perror("local-landlock-shell: install restrictions");
        close(ruleset_fd);
        free(workspace);
        free(home);
        free(xdg_config);
        free(xdg_data);
        free(xdg_state);
        free(xdg_cache);
        return 70;
    }
    close(ruleset_fd);

    if (chdir(workspace) < 0) {
        perror("local-landlock-shell: enter workspace");
        free(workspace);
        free(home);
        free(xdg_config);
        free(xdg_data);
        free(xdg_state);
        free(xdg_cache);
        return 71;
    }
    if (clearenv() < 0 || setenv("PATH", "/usr/local/bin:/usr/bin:/bin", 1) < 0 ||
        setenv("HOME", home && *home ? home : workspace, 1) < 0 ||
        setenv("TMPDIR", workspace, 1) < 0 || setenv("NO_COLOR", "1", 1) < 0 ||
        setenv("PYTHONDONTWRITEBYTECODE", "1", 1) < 0 ||
        setenv("LANG", "C.UTF-8", 1) < 0 ||
        preserve_env("XDG_CONFIG_HOME", xdg_config) < 0 ||
        preserve_env("XDG_DATA_HOME", xdg_data) < 0 ||
        preserve_env("XDG_STATE_HOME", eval_state_home && *eval_state_home ? eval_state_home : xdg_state) < 0 ||
        preserve_env("XDG_CACHE_HOME", xdg_cache) < 0) {
        fputs("local-landlock-shell: could not prepare a sanitized tool environment\n", stderr);
        free(workspace);
        free(home);
        free(xdg_config);
        free(xdg_data);
        free(xdg_state);
        free(xdg_cache);
        return 71;
    }
    free(eval_state_home);
    free(workspace);
    free(home);
    free(xdg_config);
    free(xdg_data);
    free(xdg_state);
    free(xdg_cache);

    argv[0] = "/usr/bin/bash";
    execv(argv[0], argv);
    perror("local-landlock-shell: execute bash");
    return 72;
}
