# mcp-google-sheets: A Google Sheets MCP server

This MCP server integrates with your Google Drive and Google Sheets, to enable creating and modifying spreadsheets.

## Overview

A Model Context Protocol server for interacting with Google Sheets. This server provides tools to create, read, update, and manage spreadsheets through the Google Sheets API.

### Tools

1. `get_sheet_data`
   - Get data from a specific sheet in a Google Spreadsheet
   - Input:
     - `spreadsheet_id` (string): The ID of the spreadsheet (found in the URL)
     - `sheet` (string): The name of the sheet
     - `range` (optional string): Cell range in A1 notation (e.g., 'A1:C10')
   - Returns: A 2D array of the sheet data

2. `update_cells`
   - Update cells in a Google Spreadsheet
   - Input:
     - `spreadsheet_id` (string): The ID of the spreadsheet
     - `sheet` (string): The name of the sheet
     - `range` (string): Cell range in A1 notation
     - `data` (2D array): Values to update
   - Returns: Result of the update operation

3. `batch_update_cells`
   - Batch update multiple ranges in a Google Spreadsheet
   - Input:
     - `spreadsheet_id` (string): The ID of the spreadsheet
     - `sheet` (string): The name of the sheet
     - `ranges` (object): Dictionary mapping range strings to 2D arrays of values
   - Returns: Result of the batch update operation

4. `list_sheets`
   - List all sheets in a Google Spreadsheet
   - Input:
     - `spreadsheet_id` (string): The ID of the spreadsheet
   - Returns: List of sheet names

5. `create_spreadsheet`
   - Create a new Google Spreadsheet
   - Input:
     - `title` (string): The title of the new spreadsheet
   - Returns: Information about the newly created spreadsheet including its ID

6. `create_sheet`
   - Create a new sheet tab in an existing Google Spreadsheet
   - Input:
     - `spreadsheet_id` (string): The ID of the spreadsheet
     - `title` (string): The title for the new sheet
   - Returns: Information about the newly created sheet

7. Additional tools: `add_rows`, `add_columns`, `copy_sheet`, `rename_sheet`

### Resources

1. `spreadsheet://{spreadsheet_id}/info`
   - Get basic information about a Google Spreadsheet
   - Returns: JSON string with spreadsheet information

## Installation

### Google Cloud Platform Setup (Required)

1. Create a Google Cloud Platform project and enable the Google Sheets API:
   
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select an existing one
   - Enable the Google Sheets API
   - Configure OAuth consent screen
   - Create OAuth 2.0 Client ID credentials (Desktop application type)
   - Download the credentials JSON file and save it as `credentials.json` in your project directory

### Environment Variables (Required)

Set up these environment variables before running the server:

- `CREDENTIALS_PATH`: Path to Google OAuth credentials file (default: `credentials.json`)
- `TOKEN_PATH`: Path where the authentication token will be stored (default: `token.json`)

For Linux/Mac:
```bash
export CREDENTIALS_PATH=/path/to/your/credentials.json
export TOKEN_PATH=/path/to/your/token.json
```

For Windows:
```cmd
set CREDENTIALS_PATH=C:\path\to\your\credentials.json
set TOKEN_PATH=C:\path\to\your\token.json
```

## Running the Server

### Method 1: Using uvx (recommended for normal use)

When using [`uvx`](https://docs.astral.sh/uv/guides/tools/), you can run the server directly without installation:

```bash
# Set environment variables first
export CREDENTIALS_PATH=/path/to/your/credentials.json
export TOKEN_PATH=/path/to/your/token.json

# Then run the server
uvx mcp-google-sheets
```

### Method 2: For Development and Modifications

If you want to modify and develop the server:

1. Clone the repository:
```bash
git clone https://github.com/yourusername/mcp-google-sheets.git
cd mcp-google-sheets
```

2. Run with uv:
```bash
# Set environment variables first
export CREDENTIALS_PATH=/path/to/your/credentials.json
export TOKEN_PATH=/path/to/your/token.json

# Run directly from the project directory
uv run mcp-google-sheets
```

## Authentication

The first time you use the server, it will open a browser window to authenticate with your Google account. After authentication, a token will be saved in the location specified by the `TOKEN_PATH` environment variable.

### Usage with Claude Desktop

Add this to your `claude_desktop_config.json`:

<details>
<summary>Using uvx (for normal use)</summary>

```json
"mcpServers": {
  "google-sheets": {
    "command": "uvx",
    "args": ["mcp-google-sheets"],
    "env": {
      "CREDENTIALS_PATH": "/path/to/your/credentials.json",
      "TOKEN_PATH": "/path/to/your/token.json"
    }
  }
}
```
</details>

<details>
<summary>For development</summary>

```json
"mcpServers": {
  "mcp-google-sheets": {
    "command": "uv",
    "args": [
      "--directory",
      "/path/to/mcp-google-sheets",
      "run",
      "mcp-google-sheets"
    ],
    "env": {
      "CREDENTIALS_PATH": "/path/to/mcp-google-sheets/credentials.json",
      "TOKEN_PATH": "/path/to/mcp-google-sheets/token.json"
    },
    "disabled": false
  }
}
```
</details>


## Example Prompts for Claude

Once the MCP server is connected to Claude, you can use prompts like these:

- "Get the data from Sheet1 in my spreadsheet with ID 1A2B3C4D5E6F7G8H"
- "Add 3 rows to the beginning of Sheet2 in my spreadsheet"
- "Update cells A1:B2 in my spreadsheet with the values [[1, 2], [3, 4]]"
- "List all the sheets in my Budget spreadsheet"
- "Copy the 'March' sheet from my Q1 spreadsheet to my Annual spreadsheet and rename it to 'Q1-March'"
- "Create a new spreadsheet titled 'Budget 2024'"
- "Add a new sheet named 'Q4' to my Annual Budget spreadsheet"

## License

This MCP server is licensed under the MIT License. This means you are free to use, modify, and distribute the software, subject to the terms and conditions of the MIT License. For more details, please see the LICENSE file in the project repository.

## Credits

This project was inspired by the [kazz187/mcp-google-spreadsheet](https://github.com/kazz187/mcp-google-spreadsheet) repository and ported to Python using FastMCP.