#!/usr/bin/env python
"""
Google Spreadsheet MCP Server
A Model Context Protocol (MCP) server built with FastMCP for interacting with Google Sheets.
"""

import base64
import json
import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Union, Literal, Annotated

from pydantic import BaseModel, Field

# MCP imports
from fastmcp import FastMCP, Context
# Internal imports for custom behavior override
from fastmcp.tools.tool import FunctionTool, ToolResult

# Google API imports
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import google.auth

# --- Compatibility Layer for Removed fastMCP Internal Functions ---

def _convert_to_content(result: Any) -> List[Any]:
    """
    Convert result to content blocks (replacement for removed fastMCP function).
    Simplified implementation for basic text content.
    """
    from mcp.types import TextContent
    
    if result is None:
        return [TextContent(type="text", text="null")]
    elif isinstance(result, str):
        return [TextContent(type="text", text=result)]
    elif isinstance(result, (int, float, bool)):
        return [TextContent(type="text", text=str(result))]
    elif isinstance(result, dict):
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    elif isinstance(result, list):
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    else:
        return [TextContent(type="text", text=str(result))]

def _is_pydantic_model(obj: Any) -> bool:
    """
    Check if object is a Pydantic model type (replacement for removed fastMCP function).
    """
    try:
        from pydantic import BaseModel
        return isinstance(obj, type) and issubclass(obj, BaseModel)
    except (ImportError, TypeError):
        return False

def _is_model_instance(obj: Any) -> bool:
    """
    Check if object is a Pydantic model instance (replacement for removed fastMCP function).
    """
    try:
        from pydantic import BaseModel
        return isinstance(obj, BaseModel)
    except ImportError:
        return False


# --- Custom MCP Implementation to Control Response Behavior ---

class CustomFunctionTool(FunctionTool):
    """
    A custom FunctionTool that overrides the run method to control response generation.
    This implementation fixes the duplicate response issue by controlling when to generate
    raw text content vs structured JSON content.
    """
    async def run(self, arguments: Dict[str, Any]) -> ToolResult:
        # Check for our custom control argument (excluded from schema)
        raw_content_requested = arguments.pop("raw_content", False)

        try:
            # Execute the actual tool function
            result = await self._execute(arguments)
        except Exception as e:
            # Handle execution errors gracefully
            error_content = _convert_to_content(f"Tool execution failed: {str(e)}")
            return ToolResult(
                content=error_content,
                structured_content=None,
            )
        
        # Determine content generation strategy
        is_model = _is_model_instance(result)
        is_pydantic = _is_pydantic_model(self.returns) if hasattr(self, 'returns') else False
        
        structured_content = None
        unstructured_result = None

        # Always generate structured content unless the return type is None
        if not (hasattr(self, 'returns') and self.returns is type(None)):
            if is_model:
                # Pydantic model instance - use as-is
                structured_content = result
            elif is_pydantic:
                # Return type is Pydantic model but result isn't - wrap it
                structured_content = result
            else:
                # Regular Python types - wrap in standard structure for consistency
                structured_content = result if isinstance(result, dict) else {"result": result}

        # Generate raw text content ONLY if explicitly requested
        if raw_content_requested:
            unstructured_result = _convert_to_content(result)

        return ToolResult(
            content=unstructured_result,
            structured_content=structured_content,
        )

class CustomMCP(FastMCP):
    """
    A custom FastMCP server that uses our CustomFunctionTool for all registered tools.
    This ensures consistent response behavior across all tools in the server.
    """
    def tool(self, *args, **kwargs):
        """Override the tool decorator to use our CustomFunctionTool."""
        decorator = super().tool(*args, **kwargs)
        def wrapper(func):
            # Let FastMCP create the standard tool first
            tool_instance = decorator(func)
            
            try:
                # Create our custom tool with the same properties
                custom_tool = CustomFunctionTool(
                    name=tool_instance.name,
                    description=tool_instance.description,
                    fn=tool_instance.fn,
                    returns=getattr(tool_instance, 'returns', None),
                    parameters=getattr(tool_instance, 'parameters', None),
                )
                
                # Copy any additional attributes that might exist
                for attr in ['tags', 'enabled', 'annotations']:
                    if hasattr(tool_instance, attr):
                        setattr(custom_tool, attr, getattr(tool_instance, attr))
                
                # Register the custom tool instead of the original
                self.tools[custom_tool.name] = custom_tool
                
            except Exception as e:
                # Fallback to original tool if custom creation fails
                print(f"Warning: Could not create CustomFunctionTool for {func.__name__}: {e}")
                # The original tool is already registered by the parent decorator
                pass
            
            return func # Return the original function, as is standard
        return wrapper


# --- Schema Definitions ---

CellValue = Union[str, int, float, bool, None]
QueryDict = Dict[str, str]
RecipientDict = Dict[str, str]

class SpreadsheetData(BaseModel):
    rows: List[List[CellValue]] = Field(
        description='A JSON object containing a "rows" key, which holds a 2D array of values. Example: {"rows": [["Cell A1", "Cell B1"], ["Cell A2", "Cell B2"]]}. Each cell can be a string, number, boolean, or null.'
    )

class BatchRanges(BaseModel):
    ranges: Dict[str, List[List[CellValue]]] = Field(
        description='A JSON object containing a "ranges" key, which maps range strings to a 2D array of values. Example: {"ranges": {"A1:B2": [["John", 25], ["Jane", 30]]}}'
    )


# --- Authentication and Lifespan Management ---

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
CREDENTIALS_CONFIG = os.environ.get('CREDENTIALS_CONFIG')
TOKEN_PATH = os.environ.get('TOKEN_PATH', 'token.json')
CREDENTIALS_PATH = os.environ.get('CREDENTIALS_PATH', 'credentials.json')
SERVICE_ACCOUNT_PATH = os.environ.get('SERVICE_ACCOUNT_PATH', 'service_account.json')
DRIVE_FOLDER_ID = os.environ.get('DRIVE_FOLDER_ID', '')

@dataclass
class SpreadsheetContext:
    sheets_service: Any
    drive_service: Any
    folder_id: Optional[str] = None

@asynccontextmanager
async def spreadsheet_lifespan(server: FastMCP) -> AsyncIterator[SpreadsheetContext]:
    creds = None
    auth_method = "Unknown"
    # (Authentication logic remains the same as before)
    if CREDENTIALS_CONFIG:
        try:
            service_account_info = json.loads(base64.b64decode(CREDENTIALS_CONFIG))
            creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
            auth_method = "Base64 Service Account"
        except Exception as e:
            print(f"Error with CREDENTIALS_CONFIG: {e}")
            creds = None
    if not creds and SERVICE_ACCOUNT_PATH and os.path.exists(SERVICE_ACCOUNT_PATH):
        try:
            creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_PATH, scopes=SCOPES)
            auth_method = "Service Account File"
        except Exception as e:
            print(f"Error with service account file: {e}")
            creds = None
    if not creds:
        try:
            creds, project = google.auth.default(scopes=SCOPES)
            auth_method = "Application Default Credentials"
        except Exception as e:
            print(f"Error with ADC: {e}")
            creds = None
    if not creds:
        if os.path.exists(TOKEN_PATH):
            try:
                with open(TOKEN_PATH, 'r') as token:
                    creds = Credentials.from_authorized_user_info(json.load(token), SCOPES)
                    if creds and creds.valid:
                        auth_method = "Cached OAuth Token"
                    elif creds and creds.expired and creds.refresh_token:
                        creds.refresh(Request())
                        auth_method = "Refreshed OAuth Token"
                    else:
                        creds = None
            except Exception as e:
                print(f"Error loading cached token: {e}")
                creds = None
        if not creds:
            if not os.path.exists(CREDENTIALS_PATH):
                raise Exception(f"All authentication methods failed! Check your configuration.")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
                creds = flow.run_local_server(port=0)
                with open(TOKEN_PATH, 'w') as token:
                    token.write(creds.to_json())
                auth_method = "Interactive OAuth"
            except Exception as e:
                raise Exception(f"OAuth flow failed: {e}")
    if not creds:
        raise Exception("All authentication methods exhausted.")

    sheets_service = build('sheets', 'v4', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)
    print(f"Google Sheets MCP server ready! (Auth: {auth_method})")
    
    try:
        yield SpreadsheetContext(
            sheets_service=sheets_service,
            drive_service=drive_service,
            folder_id=DRIVE_FOLDER_ID if DRIVE_FOLDER_ID else None
        )
    finally:
        print("Google API services cleaned up")
        pass


# Initialize the CUSTOM MCP server
mcp = CustomMCP("Google Spreadsheet", 
              dependencies=["google-auth", "google-auth-oauthlib", "google-api-python-client"],
              lifespan=spreadsheet_lifespan)


# --- Tool Definitions (with raw_content parameter) ---

@mcp.tool
def get_sheet_data(spreadsheet_id: str, 
                   sheet: str,
                   range: Optional[str] = None,
                   include_grid_data: bool = False,
                   raw_content: Optional[bool] = Field(False, description="Set to true to get raw text content alongside structured JSON. For internal use.", exclude=True),
                   ctx: Context = None) -> Dict[str, Any]:
    """Get data from a specific sheet. Returns a 2D array of cell values or full grid data."""
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    full_range = f"{sheet}!{range}" if range else sheet
    if include_grid_data:
        result = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id, ranges=[full_range], includeGridData=True).execute()
        return {"grid_data": result}
    else:
        result = sheets_service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=full_range).execute()
        return {"values": result.get('values', [])}

@mcp.tool
def insert_empty_rows(spreadsheet_id: str,
                      sheet: str,
                      count: int,
                      start_row: Optional[int] = None,
                      raw_content: Optional[bool] = Field(False, description="Internal use.", exclude=True),
                      ctx: Context = None) -> Dict[str, Any]:
    """Insert empty rows into a sheet in a Google Spreadsheet."""
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_id = next((s['properties']['sheetId'] for s in spreadsheet['sheets'] if s['properties']['title'] == sheet), None)
    if sheet_id is None:
        return {"error": f"Sheet '{sheet}' not found"}
    request_body = {"requests": [{"insertDimension": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": start_row or 0, "endIndex": (start_row or 0) + count}, "inheritFromBefore": start_row is not None and start_row > 0}}]}
    result = sheets_service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=request_body).execute()
    return result

# ... (Apply the raw_content parameter to all other tools similarly) ...

@mcp.tool
def get_sheet_formulas(
    spreadsheet_id: Annotated[str, Field(description="The ID of the spreadsheet (found in the URL)")],
    sheet: Annotated[str, Field(description="The name of the sheet")],
    range: Annotated[Optional[str], Field(description="Optional cell range in A1 notation")] = None,
    raw_content: Optional[bool] = Field(False, description="Internal use.", exclude=True),
    ctx: Context = None
) -> Dict[str, List[List[str]]]:
    """Get formulas from a specific sheet in a Google Spreadsheet."""
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    full_range = f"{sheet}!{range}" if range else sheet
    result = sheets_service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=full_range, valueRenderOption='FORMULA').execute()
    return {"formulas": result.get('values', [])}

@mcp.tool
def update_cells(
    spreadsheet_id: Annotated[str, Field(description="The ID of the spreadsheet (found in the URL)")],
    sheet: Annotated[str, Field(description="The name of the sheet")],
    range: Annotated[str, Field(description="Cell range in A1 notation (e.g., 'A1:C10')")],
    data: SpreadsheetData,
    raw_content: Optional[bool] = Field(False, description="Internal use.", exclude=True),
    ctx: Context = None
) -> Dict[str, Any]:
    """Update cells in a Google Spreadsheet."""
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    full_range = f"{sheet}!{range}"
    value_range_body = {'values': data.rows}
    result = sheets_service.spreadsheets().values().update(spreadsheetId=spreadsheet_id, range=full_range, valueInputOption='USER_ENTERED', body=value_range_body).execute()
    return result

@mcp.tool
def batch_update_cells(
    spreadsheet_id: Annotated[str, Field(description="The ID of the spreadsheet (found in the URL)")],
    sheet: Annotated[str, Field(description="The name of the sheet")],
    ranges: BatchRanges,
    raw_content: Optional[bool] = Field(False, description="Internal use.", exclude=True),
    ctx: Context = None
) -> Dict[str, Any]:
    """Batch update multiple ranges in a Google Spreadsheet."""
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    data = [{'range': f"{sheet}!{range_str}", 'values': values} for range_str, values in ranges.ranges.items()]
    batch_body = {'valueInputOption': 'USER_ENTERED', 'data': data}
    result = sheets_service.spreadsheets().values().batchUpdate(spreadsheetId=spreadsheet_id, body=batch_body).execute()
    return result

@mcp.tool
def add_rows(
    spreadsheet_id: Annotated[str, Field(description="The ID of the spreadsheet (found in the URL)")],
    sheet: Annotated[str, Field(description="The name of the sheet")],
    data: SpreadsheetData,
    raw_content: Optional[bool] = Field(False, description="Internal use.", exclude=True),
    ctx: Context = None
) -> Dict[str, Any]:
    """Append rows to the end of a sheet (after the last row with data)."""
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    value_range_body = {'values': data.rows}
    result = sheets_service.spreadsheets().values().append(spreadsheetId=spreadsheet_id, range=sheet, valueInputOption='USER_ENTERED', body=value_range_body).execute()
    return result

@mcp.tool
def add_columns(spreadsheet_id: str,
                sheet: str,
                count: int,
                start_column: Optional[int] = None,
                raw_content: Optional[bool] = Field(False, description="Internal use.", exclude=True),
                ctx: Context = None) -> Dict[str, Any]:
    """Add columns to a sheet in a Google Spreadsheet."""
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_id = next((s['properties']['sheetId'] for s in spreadsheet['sheets'] if s['properties']['title'] == sheet), None)
    if sheet_id is None:
        return {"error": f"Sheet '{sheet}' not found"}
    request_body = {"requests": [{"insertDimension": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": start_column or 0, "endIndex": (start_column or 0) + count}, "inheritFromBefore": start_column is not None and start_column > 0}}]}
    result = sheets_service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=request_body).execute()
    return result

@mcp.tool
def list_sheets(spreadsheet_id: str, 
                raw_content: Optional[bool] = Field(False, description="Internal use.", exclude=True),
                ctx: Context = None) -> Dict[str, List[str]]:
    """List all sheets in a Google Spreadsheet."""
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_names = [sheet['properties']['title'] for sheet in spreadsheet['sheets']]
    return {"sheets": sheet_names}

@mcp.tool
def copy_sheet(src_spreadsheet: str,
               src_sheet: str,
               dst_spreadsheet: str,
               dst_sheet: str,
               raw_content: Optional[bool] = Field(False, description="Internal use.", exclude=True),
               ctx: Context = None) -> Dict[str, Any]:
    """Copy a sheet from one spreadsheet to another."""
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    src = sheets_service.spreadsheets().get(spreadsheetId=src_spreadsheet).execute()
    src_sheet_id = next((s['properties']['sheetId'] for s in src['sheets'] if s['properties']['title'] == src_sheet), None)
    if src_sheet_id is None:
        return {"error": f"Source sheet '{src_sheet}' not found"}
    copy_result = sheets_service.spreadsheets().sheets().copyTo(spreadsheetId=src_spreadsheet, sheetId=src_sheet_id, body={"destinationSpreadsheetId": dst_spreadsheet}).execute()
    if 'title' in copy_result and copy_result['title'] != dst_sheet:
        copy_sheet_id = copy_result['sheetId']
        rename_request = {"requests": [{"updateSheetProperties": {"properties": {"sheetId": copy_sheet_id, "title": dst_sheet}, "fields": "title"}}]}
        rename_result = sheets_service.spreadsheets().batchUpdate(spreadsheetId=dst_spreadsheet, body=rename_request).execute()
        return {"copy": copy_result, "rename": rename_result}
    return {"copy": copy_result}

@mcp.tool
def rename_sheet(spreadsheet: str,
                 sheet: str,
                 new_name: str,
                 raw_content: Optional[bool] = Field(False, description="Internal use.", exclude=True),
                 ctx: Context = None) -> Dict[str, Any]:
    """Rename a sheet in a Google Spreadsheet."""
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    spreadsheet_data = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet).execute()
    sheet_id = next((s['properties']['sheetId'] for s in spreadsheet_data['sheets'] if s['properties']['title'] == sheet), None)
    if sheet_id is None:
        return {"error": f"Sheet '{sheet}' not found"}
    request_body = {"requests": [{"updateSheetProperties": {"properties": {"sheetId": sheet_id, "title": new_name}, "fields": "title"}}]}
    result = sheets_service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet, body=request_body).execute()
    return result

@mcp.tool
def get_multiple_sheet_data(
    queries: Annotated[List[Dict[str, str]], Field(description="A list of query dictionaries with 'spreadsheet_id', 'sheet', and 'range' keys")],
    raw_content: Optional[bool] = Field(False, description="Internal use.", exclude=True),
    ctx: Context = None
) -> List[Dict[str, Any]]:
    """Get data from multiple specific ranges in Google Spreadsheets."""
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    results = []
    for query in queries:
        spreadsheet_id = query.get('spreadsheet_id')
        sheet = query.get('sheet')
        range_str = query.get('range')
        if not all([spreadsheet_id, sheet, range_str]):
            results.append({**query, 'error': 'Missing required keys'})
            continue
        try:
            full_range = f"{sheet}!{range_str}"
            result = sheets_service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=full_range).execute()
            results.append({**query, 'data': result.get('values', [])})
        except Exception as e:
            results.append({**query, 'error': str(e)})
    return results

@mcp.tool
def get_multiple_spreadsheet_summary(
    spreadsheet_ids: Annotated[List[str], Field(description="A list of spreadsheet IDs to summarize")],
    rows_to_fetch: Annotated[int, Field(description="Number of rows to fetch for summary", ge=1)] = 5,
    raw_content: Optional[bool] = Field(False, description="Internal use.", exclude=True),
    ctx: Context = None
) -> List[Dict[str, Any]]:
    """Get a summary of multiple Google Spreadsheets."""
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    summaries = []
    for spreadsheet_id in spreadsheet_ids:
        summary_data = {'spreadsheet_id': spreadsheet_id, 'title': None, 'sheets': [], 'error': None}
        try:
            spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields='properties.title,sheets(properties(title,sheetId))').execute()
            summary_data['title'] = spreadsheet.get('properties', {}).get('title', 'Unknown Title')
            sheet_summaries = []
            for sheet in spreadsheet.get('sheets', []):
                sheet_title = sheet.get('properties', {}).get('title')
                sheet_summary = {'title': sheet_title, 'headers': [], 'first_rows': [], 'error': None}
                if not sheet_title:
                    sheet_summary['error'] = 'Sheet title not found'
                else:
                    try:
                        range_to_get = f"{sheet_title}!A1:{max(1, rows_to_fetch)}"
                        result = sheets_service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_to_get).execute()
                        values = result.get('values', [])
                        if values:
                            sheet_summary['headers'] = values[0]
                            if len(values) > 1:
                                sheet_summary['first_rows'] = values[1:max(1, rows_to_fetch)]
                    except Exception as sheet_e:
                        sheet_summary['error'] = f'Error fetching data for sheet {sheet_title}: {sheet_e}'
                sheet_summaries.append(sheet_summary)
            summary_data['sheets'] = sheet_summaries
        except Exception as e:
            summary_data['error'] = f'Error fetching spreadsheet {spreadsheet_id}: {e}'
        summaries.append(summary_data)
    return summaries

@mcp.tool
def create_spreadsheet(title: str,
                       raw_content: Optional[bool] = Field(False, description="Internal use.", exclude=True),
                       ctx: Context = None) -> Dict[str, Any]:
    """Create a new Google Spreadsheet."""
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    drive_service = ctx.request_context.lifespan_context.drive_service
    folder_id = ctx.request_context.lifespan_context.folder_id
    spreadsheet_body = {'properties': {'title': title}}
    spreadsheet = sheets_service.spreadsheets().create(body=spreadsheet_body, fields='spreadsheetId,properties,sheets').execute()
    spreadsheet_id = spreadsheet.get('spreadsheetId')
    if folder_id:
        try:
            file = drive_service.files().get(fileId=spreadsheet_id, fields='parents').execute()
            previous_parents = ",".join(file.get('parents', []))
            drive_service.files().update(fileId=spreadsheet_id, addParents=folder_id, removeParents=previous_parents, fields='id, parents').execute()
        except Exception as e:
            print(f"Warning: Could not move spreadsheet to folder: {e}")
    return {'spreadsheetId': spreadsheet_id, 'title': spreadsheet.get('properties', {}).get('title', title), 'folder': folder_id or 'root'}

@mcp.tool
def create_sheet(spreadsheet_id: str, 
                title: str,
                raw_content: Optional[bool] = Field(False, description="Internal use.", exclude=True),
                ctx: Context = None) -> Dict[str, Any]:
    """Create a new sheet tab in an existing Google Spreadsheet."""
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    request_body = {"requests": [{"addSheet": {"properties": {"title": title}}}]}
    result = sheets_service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=request_body).execute()
    new_sheet_props = result['replies'][0]['addSheet']['properties']
    return {'sheetId': new_sheet_props['sheetId'], 'title': new_sheet_props['title'], 'spreadsheetId': spreadsheet_id}

@mcp.tool
def list_spreadsheets(
    raw_content: Optional[bool] = Field(False, description="Internal use.", exclude=True),
    ctx: Context = None) -> Dict[str, List[Dict[str, str]]]:
    """List all spreadsheets in the configured Google Drive folder or 'My Drive'."""
    drive_service = ctx.request_context.lifespan_context.drive_service
    folder_id = ctx.request_context.lifespan_context.folder_id
    query = "mimeType='application/vnd.google-apps.spreadsheet'"
    if folder_id:
        query += f" and '{folder_id}' in parents"
    results = drive_service.files().list(q=query, spaces='drive', fields='files(id, name)', orderBy='modifiedTime desc').execute()
    return {"spreadsheets": [{'id': sheet['id'], 'title': sheet['name']} for sheet in results.get('files', [])]}

@mcp.tool
def share_spreadsheet(
    spreadsheet_id: Annotated[str, Field(description="The ID of the spreadsheet to share")], 
    recipients: Annotated[List[Dict[str, str]], Field(description="List of recipients with 'email_address' and 'role' keys")],
    send_notification: Annotated[bool, Field(description="Whether to send notification emails")] = True,
    raw_content: Optional[bool] = Field(False, description="Internal use.", exclude=True),
    ctx: Context = None
) -> Dict[str, List[Dict[str, Any]]]:
    """Share a Google Spreadsheet with multiple users via email, assigning specific roles."""
    drive_service = ctx.request_context.lifespan_context.drive_service
    successes, failures = [], []
    for recipient in recipients:
        email, role = recipient.get('email_address'), recipient.get('role', 'writer')
        if not email or role not in ['reader', 'commenter', 'writer']:
            failures.append({'email_address': email, 'error': 'Invalid recipient data'})
            continue
        permission = {'type': 'user', 'role': role, 'emailAddress': email}
        try:
            result = drive_service.permissions().create(fileId=spreadsheet_id, body=permission, sendNotificationEmail=send_notification, fields='id').execute()
            successes.append({'email_address': email, 'role': role, 'permissionId': result.get('id')})
        except Exception as e:
            failures.append({'email_address': email, 'error': f"Failed to share: {e}"})
    return {"successes": successes, "failures": failures}

def main():
    mcp.run()

if __name__ == "__main__":
    main()
