# Local PC-project workflow

Choose your own game in **New project**, select the required options and generate
its native PC source. The output is tracked in **Projects** across app restarts.
Open its project page to open the folder, read its generated README, copy CMake
build commands or check source integrity. Prepare assets and prerequisites as
the generated README explains before configuring or building.

**Add an existing PC project** accepts a local folder containing
`pc-project.json`, including earlier exports, CLI outputs and edited projects.
The app records a changed or missing source file as a difference from the
generated manifest. Your edits remain intact. An integrity pass establishes
that the original generated files match their manifest; it does not establish
a successful host build or a full playthrough. Build and gameplay checks remain
separate. Removing a project from the list only removes its entry, never files,
assets or saves. If a folder moves, add its new location and remove the old entry.

Public-project browsing/imports, team rooms, invitations, sharing servers,
tunnels and the `host`, `join` and `share` commands have been removed. Existing
local source-recovery projects and private work remain on disk. Console matching
is an advanced workflow separate from native PC output.

## Your own agent

Use **Connect your own agent**, or run `decomp connect` from the application
environment. Claude Code, Codex, Antigravity CLI and opencode can register the
stdio MCP bridge. Other MCP clients can use the JSON shown in the connection
dialog. The bridge uses this installation's Python interpreter and the same
absolute `DECOMP_HOME` workspace as the GUI. It mints a local agent identity
when connecting; the registration contains no session token.

Use **Reconnect** after moving the installation or changing workspaces. For
opencode, an existing valid JSON configuration and other MCP entries are
preserved. JSON-with-comments configurations require the manual configuration
shown by the app; they are not overwritten.

Ask your agent to generate a native PC project from your own game. Its tools
include `generate_pc_project`, `list_projects`, `open_project`,
`inspect_pc_project`, `verify_pc_project` and `open_gui`. Native outputs open on
their PC-project page. Your agent edits and builds the exported folder with its
own coding tools. Matching-loop helpers apply to console recovery projects and
cannot accidentally start against a native output. Connected agents can send
source to the provider you choose; connecting an agent does not start helpers.

The native workflow does not require an agent. Agent registration and API-model
setup remain optional.
