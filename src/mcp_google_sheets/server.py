#!/usr/bin/env python
"""
Google Spreadsheet MCP Server
A Model Context Protocol (MCP) server built with FastMCP for interacting with Google Sheets.
"""

import base64
import os
from typing import List, Dict, Any, Optional, Union, Literal, Annotated
from pydantic import BaseModel, Field
import json
from dataclasses import dataclass
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

# Schema improvements: Add more specific type definitions
# Clarify 2D array type definitions
CellValue = Union[str, int, float, bool, None]
QueryDict = Dict[str, str]  # Query dictionary containing spreadsheet_id, sheet, range
RecipientDict = Dict[str, str]  # Recipient dictionary containing email_address, role

# Define Pydantic BaseModel for 2D array with proper JSON schema generation
class SpreadsheetData(BaseModel):
    """A JSON object that wraps a 2D array of spreadsheet data."""
    rows: List[List[Union[str, int, float, bool, None]]] = Field(
        description='A JSON object containing a "rows" key, which holds a 2D array of values. Example: {\"rows": [["Cell A1", "Cell B1\"], ["Cell A2", \"Cell B2\"]]}. Each cell can be a string, number, boolean, or null.'
    )

# Define Pydantic BaseModel for batch ranges
class BatchRanges(BaseModel):
    """A JSON object for batch updating multiple ranges with their corresponding data."""
    ranges: Dict[str, List[List[Union[str, int, float, bool, None]]]] = Field(
        description='A JSON object containing a "ranges" key, which maps range strings to a 2D array of values. Example: {\"ranges": {\"A1:B2\\": [[\"John", 25], [\"Jane\\", 30]]}}'
    )

# MCP imports
from fastmcp import FastMCP, Context

# Google API imports
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import google.auth

# Constants
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
CREDENTIALS_CONFIG = os.environ.get('CREDENTIALS_CONFIG')
TOKEN_PATH = os.environ.get('TOKEN_PATH', 'token.json')
CREDENTIALS_PATH = os.environ.get('CREDENTIALS_PATH', 'credentials.json')
SERVICE_ACCOUNT_PATH = os.environ.get('SERVICE_ACCOUNT_PATH', 'service_account.json')
DRIVE_FOLDER_ID = os.environ.get('DRIVE_FOLDER_ID', '')  # Working directory in Google Drive

@dataclass
class SpreadsheetContext:
    """Context for Google Spreadsheet service"""
    sheets_service: Any
    drive_service: Any
    folder_id: Optional[str] = None


@asynccontextmanager
async def spreadsheet_lifespan(server: FastMCP) -> AsyncIterator[SpreadsheetContext]:
    """Manage Google Spreadsheet API connection lifecycle"""
    creds = None
    auth_method = "Unknown"
    
    # Method 1: CREDENTIALS_CONFIG (Base64 service account)
    if CREDENTIALS_CONFIG:
        try:
            print("Attempting authentication with CREDENTIALS_CONFIG (Base64 service account)...")
            service_account_info = json.loads(base64.b64decode(CREDENTIALS_CONFIG))
            creds = service_account.Credentials.from_service_account_info(
                service_account_info, 
                scopes=SCOPES
            )
            auth_method = "Base64 Service Account"
            print(f"✅ Successfully authenticated using {auth_method}")
            print(f"📁 Working with Google Drive folder ID: {DRIVE_FOLDER_ID or 'Not specified'}")
        except Exception as e:
            print(f"❌ Error with CREDENTIALS_CONFIG: {e}")
            creds = None
    
    # Method 2: SERVICE_ACCOUNT_PATH (Service account file)
    if not creds and SERVICE_ACCOUNT_PATH and os.path.exists(SERVICE_ACCOUNT_PATH):
        try:
            print(f"Attempting authentication with SERVICE_ACCOUNT_PATH: {SERVICE_ACCOUNT_PATH}...")
            creds = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_PATH,
                scopes=SCOPES
            )
            auth_method = "Service Account File"
            print(f"✅ Successfully authenticated using {auth_method}")
            print(f"📁 Working with Google Drive folder ID: {DRIVE_FOLDER_ID or 'Not specified'}")
        except Exception as e:
            print(f"❌ Error with service account file: {e}")
            creds = None
    
    # Method 3: Application Default Credentials (ADC)
    if not creds:
        try:
            print("Attempting Application Default Credentials (ADC)...")
            print("🔍 ADC will check: GOOGLE_APPLICATION_CREDENTIALS, gcloud auth, metadata service")
            creds, project = google.auth.default(scopes=SCOPES)
            auth_method = "Application Default Credentials"
            print(f"✅ Successfully authenticated using {auth_method} for project: {project}")
        except Exception as e:
            print(f"❌ Error with ADC: {e}")
            creds = None
    
    # Method 4: OAuth 2.0 Flow (last resort - requires user interaction)
    if not creds:
        print("⚠️  All automated authentication methods failed.")
        print("🔄 Attempting OAuth 2.0 flow (requires user interaction)...")
        
        # Check for existing token
        if os.path.exists(TOKEN_PATH):
            try:
                with open(TOKEN_PATH, 'r') as token:
                    creds = Credentials.from_authorized_user_info(json.load(token), SCOPES)
                    if creds and creds.valid:
                        auth_method = "Cached OAuth Token"
                        print(f"✅ Using cached OAuth token")
                    elif creds and creds.expired and creds.refresh_token:
                        print("🔄 Refreshing expired OAuth token...")
                        creds.refresh(Request())
                        auth_method = "Refreshed OAuth Token"
                        print(f"✅ Successfully refreshed OAuth token")
                    else:
                        creds = None
            except Exception as e:
                print(f"❌ Error loading cached token: {e}")
                creds = None
        
        # If still no valid credentials, try interactive OAuth flow
        if not creds:
            if not os.path.exists(CREDENTIALS_PATH):
                raise Exception(
                    f"❌ All authentication methods failed!\n"
                    f"📋 Tried: CREDENTIALS_CONFIG, SERVICE_ACCOUNT_PATH, ADC, OAuth\n"
                    f"🔧 Solutions:\n"
                    f"   1. Ensure CREDENTIALS_CONFIG is valid Base64-encoded service account\n"
                    f"   2. Create service account file at: {SERVICE_ACCOUNT_PATH}\n"
                    f"   3. Run 'gcloud auth application-default login'\n"
                    f"   4. Create OAuth credentials at: {CREDENTIALS_PATH}\n"
                    f"📚 See: https://github.com/xing5/mcp-google-sheets#authentication"
                )
            
            try:
                print(f"🔄 Starting interactive OAuth flow (credentials from: {CREDENTIALS_PATH})...")
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
                creds = flow.run_local_server(port=0)
                
                # Save the credentials for next time
                with open(TOKEN_PATH, 'w') as token:
                    token.write(creds.to_json())
                    
                auth_method = "Interactive OAuth"
                print(f"✅ Successfully completed OAuth flow")
            except Exception as e:
                raise Exception(
                    f"❌ OAuth flow failed: {e}\n"
                    f"🌐 This error often indicates network connectivity issues\n"
                    f"🔧 Solutions:\n"
                    f"   1. Check internet connection\n"
                    f"   2. Verify firewall settings\n"
                    f"   3. Try using service account authentication instead\n"
                    f"   4. Check if oauth2.googleapis.com is accessible"
                )
    
    if not creds:
        raise Exception("All authentication methods exhausted. Please check your configuration.")
    
    # Build the services
    print(f"🔄 Building Google API services...")
    sheets_service = build('sheets', 'v4', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)
    print(f"🚀 Google Sheets MCP server ready! (Auth: {auth_method})")
    
    try:
        # Provide the service in the context
        yield SpreadsheetContext(
            sheets_service=sheets_service,
            drive_service=drive_service,
            folder_id=DRIVE_FOLDER_ID if DRIVE_FOLDER_ID else None
        )
    finally:
        # No explicit cleanup needed for Google APIs
        print("💭 Google API services cleaned up")
        pass


# Initialize the MCP server with lifespan management
mcp = FastMCP("Google Spreadsheet", 
              dependencies=["google-auth", "google-auth-oauthlib", "google-api-python-client"],
              lifespan=spreadsheet_lifespan)


@mcp.tool
def get_sheet_data(spreadsheet_id: str, 
                   sheet: str,
                   range: Optional[str] = None,
                   include_grid_data: bool = False,
                   ctx: Context = None) -> Union[List[List[CellValue]], Dict[str, Any]]:
    """
    Get data from a specific sheet. By default, returns a 2D array of cell values.
    
    This tool is optimized for efficiency. For detailed metadata, set `include_grid_data` to True.
    
    Args:
        spreadsheet_id: The ID of the spreadsheet (found in the URL).
        sheet: The name of the sheet.
        range: Optional cell range in A1 notation (e.g., 'A1:C10'). Gets all data if not provided.
        include_grid_data: If True, returns the full grid data object from Google API, including
                           formatting and other metadata. Defaults to False.
    
    Returns:
        - If `include_grid_data` is False (default): A 2D array (list of lists) of cell values.
        - If `include_grid_data` is True: A dictionary with the full grid data from the API.
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    
    # Construct the range
    full_range = f"{sheet}!{range}" if range else sheet
    
    if include_grid_data:
        # Fetch full grid data, including formatting and metadata
        result = sheets_service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            ranges=[full_range],
            includeGridData=True
        ).execute()
        return result
    else:
        # Fetch only cell values for efficiency
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=full_range
        ).execute()
        return result.get('values', [])


@mcp.tool
def insert_empty_rows(spreadsheet_id: str,
                      sheet: str,
                      count: int,
                      start_row: Optional[int] = None,
                      ctx: Context = None) -> Dict[str, Any]:
    """
    Insert empty rows into a sheet in a Google Spreadsheet.
    
    Args:
        spreadsheet_id: The ID of the spreadsheet (found in the URL)
        sheet: The name of the sheet
        count: Number of empty rows to insert
        start_row: 0-based row index to start inserting. If not provided, inserts at the end.
    
    Returns:
        Result of the operation
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    
    # Get sheet ID
    spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_id = None
    
    for s in spreadsheet['sheets']:
        if s['properties']['title'] == sheet:
            sheet_id = s['properties']['sheetId']
            break
            
    if sheet_id is None:
        return {"error": f"Sheet '{sheet}' not found"}
    
    # Prepare the insert rows request
    request_body = {
        "requests": [
            {
                "insertDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": start_row if start_row is not None else 0,
                        "endIndex": (start_row if start_row is not None else 0) + count
                    },
                    "inheritFromBefore": start_row is not None and start_row > 0
                }
            }
        ]
    }
    
    # Execute the request
    result = sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body=request_body
    ).execute()
    
    return result

@mcp.tool
def get_sheet_formulas(
    spreadsheet_id: Annotated[str, Field(description="The ID of the spreadsheet (found in the URL)")],
    sheet: Annotated[str, Field(description="The name of the sheet")],
    range: Annotated[Optional[str], Field(description="Optional cell range in A1 notation")] = None,
    ctx: Context = None
) -> List[List[str]]:
    """
    Get formulas from a specific sheet in a Google Spreadsheet.
    
    Args:
        spreadsheet_id: The ID of the spreadsheet (found in the URL)
        sheet: The name of the sheet
        range: Optional cell range in A1 notation (e.g., 'A1:C10'). If not provided, gets all formulas from the sheet.
    
    Returns:
        A 2D array of the sheet formulas where each cell contains the formula as a string.
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    
    # Construct the range
    if range:
        full_range = f"{sheet}!{range}"
    else:
        full_range = sheet  # Get all formulas in the specified sheet
    
    # Call the Sheets API
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=full_range,
        valueRenderOption='FORMULA'  # Request formulas
    ).execute()
    
    # Get the formulas from the response
    formulas = result.get('values', [])
    return formulas

@mcp.tool
def update_cells(
    spreadsheet_id: Annotated[str, Field(description="The ID of the spreadsheet (found in the URL)")],
    sheet: Annotated[str, Field(description="The name of the sheet")],
    range: Annotated[str, Field(description="Cell range in A1 notation (e.g., 'A1:C10')")],
    data: SpreadsheetData,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Update cells in a Google Spreadsheet.
    
    Args:
        spreadsheet_id: The ID of the spreadsheet (found in the URL)
        sheet: The name of the sheet
        range: Cell range in A1 notation (e.g., 'A1:C10')
        data: SpreadsheetData object. Expects a JSON like: {"rows": [["val1", "val2"]]}
    
    Returns:
        Result of the update operation
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    
    # Construct the range
    full_range = f"{sheet}!{range}"
    
    # Prepare the value range object
    value_range_body = {
        'values': data.rows
    }
    
    # Call the Sheets API to update values
    result = sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=full_range,
        valueInputOption='USER_ENTERED',
        body=value_range_body
    ).execute()
    
    return result


@mcp.tool
def batch_update_cells(
    spreadsheet_id: Annotated[str, Field(description="The ID of the spreadsheet (found in the URL)")],
    sheet: Annotated[str, Field(description="The name of the sheet")],
    ranges: BatchRanges,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Batch update multiple ranges in a Google Spreadsheet.
    
    Args:
        spreadsheet_id: The ID of the spreadsheet (found in the URL)
        sheet: The name of the sheet
        ranges: BatchRanges object. Expects a JSON like: {"ranges": {"A1:B2": [["val1"]]}}
    
    Returns:
        Result of the batch update operation
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    
    # Prepare the batch update request
    data = []
    for range_str, values in ranges.ranges.items():
        full_range = f"{sheet}!{range_str}"
        data.append({
            'range': full_range,
            'values': values
        })
    
    batch_body = {
        'valueInputOption': 'USER_ENTERED',
        'data': data
    }
    
    # Call the Sheets API to perform batch update
    result = sheets_service.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body=batch_body
    ).execute()
    
    return result


@mcp.tool
def add_rows(
    spreadsheet_id: Annotated[str, Field(description="The ID of the spreadsheet (found in the URL)")],
    sheet: Annotated[str, Field(description="The name of the sheet")],
    data: SpreadsheetData,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Append rows to the end of a sheet (after the last row with data).
    
    Args:
        spreadsheet_id: The ID of the spreadsheet (found in the URL)
        sheet: The name of the sheet
        data: SpreadsheetData object. Expects a JSON like: {"rows": [["val1", "val2"]]}
    
    Returns:
        Update result object
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    
    # Construct the range (just the sheet name for append)
    range_name = sheet
    
    # Prepare the value range object
    value_range_body = {
        'values': data.rows
    }
    
    # Call the Sheets API to append values
    result = sheets_service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption='USER_ENTERED',
        body=value_range_body
    ).execute()
    
    return result


@mcp.tool
def add_columns(spreadsheet_id: str,
                sheet: str,
                count: int,
                start_column: Optional[int] = None,
                ctx: Context = None) -> Dict[str, Any]:
    """
    Add columns to a sheet in a Google Spreadsheet.
    
    Args:
        spreadsheet_id: The ID of the spreadsheet (found in the URL)
        sheet: The name of the sheet
        count: Number of columns to add
        start_column: 0-based column index to start adding. If not provided, adds at the end.
    
    Returns:
        Result of the operation
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    
    # Get sheet ID
    spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_id = None
    
    for s in spreadsheet['sheets']:
        if s['properties']['title'] == sheet:
            sheet_id = s['properties']['sheetId']
            break
            
    if sheet_id is None:
        return {"error": f"Sheet '{sheet}' not found"}
    
    # Prepare the insert columns request
    request_body = {
        "requests": [
            {
                "insertDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": start_column if start_column is not None else 0,
                        "endIndex": (start_column if start_column is not None else 0) + count
                    },
                    "inheritFromBefore": start_column is not None and start_column > 0
                }
            }
        ]
    }
    
    # Execute the request
    result = sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body=request_body
    ).execute()
    
    return result


@mcp.tool
def list_sheets(spreadsheet_id: str, ctx: Context = None) -> List[str]:
    """
    List all sheets in a Google Spreadsheet.
    
    Args:
        spreadsheet_id: The ID of the spreadsheet (found in the URL)
    
    Returns:
        List of sheet names
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    
    # Get spreadsheet metadata
    spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    
    # Extract sheet names
    sheet_names = [sheet['properties']['title'] for sheet in spreadsheet['sheets']]
    
    return sheet_names


@mcp.tool
def copy_sheet(src_spreadsheet: str,
               src_sheet: str,
               dst_spreadsheet: str,
               dst_sheet: str,
               ctx: Context = None) -> Dict[str, Any]:
    """
    Copy a sheet from one spreadsheet to another.
    
    Args:
        src_spreadsheet: Source spreadsheet ID
        src_sheet: Source sheet name
        dst_spreadsheet: Destination spreadsheet ID
        dst_sheet: Destination sheet name
    
    Returns:
        Result of the operation
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    
    # Get source sheet ID
    src = sheets_service.spreadsheets().get(spreadsheetId=src_spreadsheet).execute()
    src_sheet_id = None
    
    for s in src['sheets']:
        if s['properties']['title'] == src_sheet:
            src_sheet_id = s['properties']['sheetId']
            break
            
    if src_sheet_id is None:
        return {"error": f"Source sheet '{src_sheet}' not found"}
    
    # Copy the sheet to destination spreadsheet
    copy_result = sheets_service.spreadsheets().sheets().copyTo(
        spreadsheetId=src_spreadsheet,
        sheetId=src_sheet_id,
        body={
            "destinationSpreadsheetId": dst_spreadsheet
        }
    ).execute()
    
    # If destination sheet name is different from the default copied name, rename it
    if 'title' in copy_result and copy_result['title'] != dst_sheet:
        # Get the ID of the newly copied sheet
        copy_sheet_id = copy_result['sheetId']
        
        # Rename the copied sheet
        rename_request = {
            "requests": [
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": copy_sheet_id,
                            "title": dst_sheet
                        },
                        "fields": "title"
                    }
                }
            ]
        }
        
        rename_result = sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=dst_spreadsheet,
            body=rename_request
        ).execute()
        
        return {
            "copy": copy_result,
            "rename": rename_result
        }
    
    return {"copy": copy_result}


@mcp.tool
def rename_sheet(spreadsheet: str,
                 sheet: str,
                 new_name: str,
                 ctx: Context = None) -> Dict[str, Any]:
    """
    Rename a sheet in a Google Spreadsheet.
    
    Args:
        spreadsheet: Spreadsheet ID
        sheet: Current sheet name
        new_name: New sheet name
    
    Returns:
        Result of the operation
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    
    # Get sheet ID
    spreadsheet_data = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet).execute()
    sheet_id = None
    
    for s in spreadsheet_data['sheets']:
        if s['properties']['title'] == sheet:
            sheet_id = s['properties']['sheetId']
            break
            
    if sheet_id is None:
        return {"error": f"Sheet '{sheet}' not found"}
    
    # Prepare the rename request
    request_body = {
        "requests": [
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "title": new_name
                    },
                    "fields": "title"
                }
            }
        ]
    }
    
    # Execute the request
    result = sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet,
        body=request_body
    ).execute()
    
    return result


@mcp.tool
def get_multiple_sheet_data(
    queries: Annotated[List[Dict[str, str]], Field(description="A list of query dictionaries, each with 'spreadsheet_id', 'sheet', and 'range' keys")],
    ctx: Context = None
) -> List[Dict[str, Any]]:
    """
    Get data from multiple specific ranges in Google Spreadsheets.
    
    Args:
        queries: A list of dictionaries, each specifying a query. 
                 Each dictionary should have 'spreadsheet_id', 'sheet', and 'range' keys.
                 Example: [{'spreadsheet_id': 'abc', 'sheet': 'Sheet1', 'range': 'A1:B5'}, 
                           {'spreadsheet_id': 'xyz', 'sheet': 'Data', 'range': 'C1:C10'}]
    
    Returns:
        A list of dictionaries, each containing the original query parameters 
        and the fetched 'data' or an 'error'.
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    results = []
    
    for query in queries:
        spreadsheet_id = query.get('spreadsheet_id')
        sheet = query.get('sheet')
        range_str = query.get('range')
        
        if not all([spreadsheet_id, sheet, range_str]):
            results.append({**query, 'error': 'Missing required keys (spreadsheet_id, sheet, range)'})
            continue

        try:
            # Construct the range
            full_range = f"{sheet}!{range_str}"
            
            # Call the Sheets API
            result = sheets_service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=full_range
            ).execute()
            
            # Get the values from the response
            values = result.get('values', [])
            results.append({**query, 'data': values})

        except Exception as e:
            results.append({**query, 'error': str(e)})
            
    return results


@mcp.tool
def get_multiple_spreadsheet_summary(
    spreadsheet_ids: Annotated[List[str], Field(description="A list of spreadsheet IDs to summarize")],
    rows_to_fetch: Annotated[int, Field(description="Number of rows to fetch for summary", ge=1)] = 5,
    ctx: Context = None
) -> List[Dict[str, Any]]:
    """
    Get a summary of multiple Google Spreadsheets, including sheet names, 
    headers, and the first few rows of data for each sheet.
    
    Args:
        spreadsheet_ids: A list of spreadsheet IDs to summarize.
        rows_to_fetch: The number of rows (including header) to fetch for the summary (default: 5).
    
    Returns:
        A list of dictionaries, each representing a spreadsheet summary. 
        Includes spreadsheet title, sheet summaries (title, headers, first rows), or an error.
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    summaries = []
    
    for spreadsheet_id in spreadsheet_ids:
        summary_data = {
            'spreadsheet_id': spreadsheet_id,
            'title': None,
            'sheets': [],
            'error': None
        }
        try:
            # Get spreadsheet metadata
            spreadsheet = sheets_service.spreadsheets().get(
                spreadsheetId=spreadsheet_id,
                fields='properties.title,sheets(properties(title,sheetId))'
            ).execute()
            
            summary_data['title'] = spreadsheet.get('properties', {}).get('title', 'Unknown Title')
            
            sheet_summaries = []
            for sheet in spreadsheet.get('sheets', []):
                sheet_title = sheet.get('properties', {}).get('title')
                sheet_id = sheet.get('properties', {}).get('sheetId')
                sheet_summary = {
                    'title': sheet_title,
                    'sheet_id': sheet_id,
                    'headers': [],
                    'first_rows': [],
                    'error': None
                }
                
                if not sheet_title:
                    sheet_summary['error'] = 'Sheet title not found'
                    sheet_summaries.append(sheet_summary)
                    continue
                    
                try:
                    # Fetch the first few rows (e.g., A1:Z5)
                    # Adjust range if fewer rows are requested
                    max_row = max(1, rows_to_fetch) # Ensure at least 1 row is fetched
                    range_to_get = f"{sheet_title}!A1:{max_row}" # Fetch all columns up to max_row
                    
                    result = sheets_service.spreadsheets().values().get(
                        spreadsheetId=spreadsheet_id,
                        range=range_to_get
                    ).execute()
                    
                    values = result.get('values', [])
                    
                    if values:
                        sheet_summary['headers'] = values[0]
                        if len(values) > 1:
                            sheet_summary['first_rows'] = values[1:max_row]
                    else:
                        # Handle empty sheets or sheets with less data than requested
                        sheet_summary['headers'] = []
                        sheet_summary['first_rows'] = []

                except Exception as sheet_e:
                    sheet_summary['error'] = f'Error fetching data for sheet {sheet_title}: {sheet_e}'
                
                sheet_summaries.append(sheet_summary)
            
            summary_data['sheets'] = sheet_summaries
            
        except Exception as e:
            summary_data['error'] = f'Error fetching spreadsheet {spreadsheet_id}: {e}'
            
        summaries.append(summary_data)
        
    return summaries


@mcp.resource("spreadsheet://{spreadsheet_id}/info")
def get_spreadsheet_info(spreadsheet_id: str) -> str:
    """
    Get basic information about a Google Spreadsheet.
    
    Args:
        spreadsheet_id: The ID of the spreadsheet
    
    Returns:
        JSON string with spreadsheet information
    """
    # Access the context through mcp.get_lifespan_context() for resources
    context = mcp.get_lifespan_context()
    sheets_service = context.sheets_service
    
    # Get spreadsheet metadata
    spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    
    # Extract relevant information
    info = {
        "title": spreadsheet.get('properties', {}).get('title', 'Unknown'),
        "sheets": [
            {
                "title": sheet['properties']['title'],
                "sheetId": sheet['properties']['sheetId'],
                "gridProperties": sheet['properties'].get('gridProperties', {})
            }
            for sheet in spreadsheet.get('sheets', [])
        ]
    }
    
    return json.dumps(info, indent=2)


@mcp.tool
def create_spreadsheet(title: str, ctx: Context = None) -> Dict[str, Any]:
    """
    Create a new Google Spreadsheet.
    
    Args:
        title: The title of the new spreadsheet
    
    Returns:
        Information about the newly created spreadsheet including its ID
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    drive_service = ctx.request_context.lifespan_context.drive_service
    folder_id = ctx.request_context.lifespan_context.folder_id
    
    # Create the spreadsheet using Sheets API
    spreadsheet_body = {
        'properties': {
            'title': title
        }
    }
    
    # Create the spreadsheet
    spreadsheet = sheets_service.spreadsheets().create(
        body=spreadsheet_body, 
        fields='spreadsheetId,properties,sheets'
    ).execute()
    
    spreadsheet_id = spreadsheet.get('spreadsheetId')
    print(f"Spreadsheet created with ID: {spreadsheet_id}")
    
    # If a folder_id is specified, move the spreadsheet to that folder
    if folder_id:
        try:
            # Get the current parents
            file = drive_service.files().get(
                fileId=spreadsheet_id, 
                fields='parents'
            ).execute()
            
            previous_parents = ",".join(file.get('parents', []))
            
            # Move the file to the specified folder
            drive_service.files().update(
                fileId=spreadsheet_id,
                addParents=folder_id,
                removeParents=previous_parents,
                fields='id, parents'
            ).execute()
            
            print(f"Spreadsheet moved to folder with ID: {folder_id}")
        except Exception as e:
            print(f"Warning: Could not move spreadsheet to folder: {e}")
    
    return {
        'spreadsheetId': spreadsheet_id,
        'title': spreadsheet.get('properties', {}).get('title', title),
        'sheets': [sheet.get('properties', {}).get('title', 'Sheet1') for sheet in spreadsheet.get('sheets', [])],
        'folder': folder_id if folder_id else 'root'
    }


@mcp.tool
def create_sheet(spreadsheet_id: str, 
                title: str, 
                ctx: Context = None) -> Dict[str, Any]:
    """
    Create a new sheet tab in an existing Google Spreadsheet.
    
    Args:
        spreadsheet_id: The ID of the spreadsheet
        title: The title for the new sheet
    
    Returns:
        Information about the newly created sheet
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    
    # Define the add sheet request
    request_body = {
        "requests": [
            {
                "addSheet": {
                    "properties": {
                        "title": title
                    }
                }
            }
        ]
    }
    
    # Execute the request
    result = sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body=request_body
    ).execute()
    
    # Extract the new sheet information
    new_sheet_props = result['replies'][0]['addSheet']['properties']
    
    return {
        'sheetId': new_sheet_props['sheetId'],
        'title': new_sheet_props['title'],
        'index': new_sheet_props.get('index'),
        'spreadsheetId': spreadsheet_id
    }


@mcp.tool
def list_spreadsheets(ctx: Context = None) -> List[Dict[str, str]]:
    """
    List all spreadsheets in the configured Google Drive folder.
    If no folder is configured, lists spreadsheets from 'My Drive'.
    
    Returns:
        List of spreadsheets with their ID and title
    """
    drive_service = ctx.request_context.lifespan_context.drive_service
    folder_id = ctx.request_context.lifespan_context.folder_id
    
    query = "mimeType='application/vnd.google-apps.spreadsheet'"
    
    # If a specific folder is configured, search only in that folder
    if folder_id:
        query += f" and '{folder_id}' in parents"
        print(f"Searching for spreadsheets in folder: {folder_id}")
    else:
        print("Searching for spreadsheets in 'My Drive'")
    
    # List spreadsheets
    results = drive_service.files().list(
        q=query,
        spaces='drive',
        fields='files(id, name)',
        orderBy='modifiedTime desc'
    ).execute()
    
    spreadsheets = results.get('files', [])
    
    return [{'id': sheet['id'], 'title': sheet['name']} for sheet in spreadsheets]


@mcp.tool
def share_spreadsheet(
    spreadsheet_id: Annotated[str, Field(description="The ID of the spreadsheet to share")], 
    recipients: Annotated[List[Dict[str, str]], Field(description="List of recipients with 'email_address' and 'role' keys")],
    send_notification: Annotated[bool, Field(description="Whether to send notification emails")] = True,
    ctx: Context = None
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Share a Google Spreadsheet with multiple users via email, assigning specific roles.
    
    Args:
        spreadsheet_id: The ID of the spreadsheet to share.
        recipients: A list of dictionaries, each containing 'email_address' and 'role'.
                    The role should be one of: 'reader', 'commenter', 'writer'.
                    Example: [
                        {'email_address': 'user1@example.com', 'role': 'writer'},
                        {'email_address': 'user2@example.com', 'role': 'reader'}
                    ]
        send_notification: Whether to send a notification email to the users. Defaults to True.

    Returns:
        A dictionary containing lists of 'successes' and 'failures'. 
        Each item in the lists includes the email address and the outcome.
    """
    drive_service = ctx.request_context.lifespan_context.drive_service
    successes = []
    failures = []
    
    for recipient in recipients:
        email_address = recipient.get('email_address')
        role = recipient.get('role', 'writer') # Default to writer if role is missing for an entry
        
        if not email_address:
            failures.append({
                'email_address': None,
                'error': 'Missing email_address in recipient entry.'
            })
            continue
            
        if role not in ['reader', 'commenter', 'writer']:
             failures.append({
                'email_address': email_address,
                'error': f"Invalid role '{role}'. Must be 'reader', 'commenter', or 'writer'."
            })
             continue

        permission = {
            'type': 'user',
            'role': role,
            'emailAddress': email_address
        }
        
        try:
            result = drive_service.permissions().create(
                fileId=spreadsheet_id,
                body=permission,
                sendNotificationEmail=send_notification,
                fields='id'
            ).execute()
            successes.append({
                'email_address': email_address, 
                'role': role, 
                'permissionId': result.get('id')
            })
        except Exception as e:
            # Try to provide a more informative error message
            error_details = str(e)
            if hasattr(e, 'content'):
                try:
                    error_content = json.loads(e.content)
                    error_details = error_content.get('error', {}).get('message', error_details)
                except json.JSONDecodeError:
                    pass # Keep the original error string
            failures.append({
                'email_address': email_address,
                'error': f"Failed to share: {error_details}"
            })
            
    return {"successes": successes, "failures": failures}

def main():
    # Run the server
    mcp.run()
