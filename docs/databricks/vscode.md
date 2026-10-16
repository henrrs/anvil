# VS Code and Databricks

The official Databricks VS Code extension is identified as `databricks.databricks`. When the public `code` command is available, Anvil checks installed extension IDs with `code --list-extensions`. It does not inspect extension directories, internal databases, private credential stores, or extension APIs.

VS Code is an assisted provider. It can help a user sign in, select a workspace/compute, browse Unity Catalog, edit workspace files, use notebook workflows, configure Databricks Connect, and work with Bundles. It is not a headless API for Anvil's SQL or Python execution contracts.

Anvil detects VS Code local and remote contexts from several environment/path signals. A local VS Code terminal can use the normal local CLI flow. For VS Code Remote, Anvil does not assume the remote process can receive a browser's local loopback callback. Azure workspaces may use the supported Azure CLI device-code flow through the SDK; AWS/GCP workspaces are guided to an existing supported profile or this extension's sign-in flow. After extension sign-in, rerun `make databricks-setup` so Anvil can validate the resulting supported profile. No command-palette clicks, panel scraping, menu automation, or automatic extension installation is used.

The extension supports multiple development paths; availability and workspace policy determine which apply. See the [official extension authentication guide](https://docs.databricks.com/aws/en/dev-tools/vscode-ext/authentication) and [Marketplace entry](https://marketplace.visualstudio.com/items?itemName=databricks.databricks).
