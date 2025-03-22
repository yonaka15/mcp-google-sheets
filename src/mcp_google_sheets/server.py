#!/usr/bin/env python
"""
Google Spreadsheet MCP Server
A Model Context Protocol (MCP) server built with FastMCP for interacting with Google Sheets.
"""

import os
from typing import List, Dict, Any, Optional, Union
import json
from dataclasses import dataclass
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

# MCP imports
from mcp.server.fastmcp import FastMCP, Context

# Google API imports
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Constants
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
TOKEN_PATH = os.environ.get('TOKEN_PATH', 'token.json')
CREDENTIALS_PATH = os.environ.get('CREDENTIALS_PATH', 'credentials.json')


@dataclass
class SpreadsheetContext:
    """Context for Google Spreadsheet service"""
    sheets_service: Any


@asynccontextmanager
async def spreadsheet_lifespan(server: FastMCP) -> AsyncIterator[SpreadsheetContext]:
    """Manage Google Spreadsheet API connection lifecycle"""
    # Authenticate and build the service
    creds = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, 'r') as token:
            creds = Credentials.from_authorized_user_info(json.load(token), SCOPES)
            
    # If credentials are not valid or don't exist, get new ones
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())
    
    # Build the service
    service = build('sheets', 'v4', credentials=creds)
    sheets_service = service.spreadsheets()
    
    try:
        # Provide the service in the context
        yield SpreadsheetContext(sheets_service=sheets_service)
    finally:
        # No explicit cleanup needed for Google Sheets API
        pass


# Initialize the MCP server with lifespan management
mcp = FastMCP("Google Spreadsheet", 
              dependencies=["google-auth", "google-auth-oauthlib", "google-api-python-client"],
              lifespan=spreadsheet_lifespan)


@mcp.tool()
def get_sheet_data(spreadsheet_id: str, 
                   sheet: str,
                   range: Optional[str] = None,
                   ctx: Context = None) -> List[List[Any]]:
    """
    Get data from a specific sheet in a Google Spreadsheet.
    
    Args:
        spreadsheet_id: The ID of the spreadsheet (found in the URL)
        sheet: The name of the sheet
        range: Optional cell range in A1 notation (e.g., 'A1:C10'). If not provided, gets all data.
    
    Returns:
        A 2D array of the sheet data
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    
    # Construct the range
    if range:
        full_range = f"{sheet}!{range}"
    else:
        full_range = sheet
    
    # Call the Sheets API
    result = sheets_service.values().get(
        spreadsheetId=spreadsheet_id,
        range=full_range
    ).execute()
    
    # Get the values from the response
    values = result.get('values', [])
    return values


@mcp.tool()
def update_cells(spreadsheet_id: str,
                sheet: str,
                range: str,
                data: List[List[Any]],
                ctx: Context = None) -> Dict[str, Any]:
    """
    Update cells in a Google Spreadsheet.
    
    Args:
        spreadsheet_id: The ID of the spreadsheet (found in the URL)
        sheet: The name of the sheet
        range: Cell range in A1 notation (e.g., 'A1:C10')
        data: 2D array of values to update
    
    Returns:
        Result of the update operation
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    
    # Construct the range
    full_range = f"{sheet}!{range}"
    
    # Prepare the value range object
    value_range_body = {
        'values': data
    }
    
    # Call the Sheets API to update values
    result = sheets_service.values().update(
        spreadsheetId=spreadsheet_id,
        range=full_range,
        valueInputOption='USER_ENTERED',
        body=value_range_body
    ).execute()
    
    return result


@mcp.tool()
def batch_update_cells(spreadsheet_id: str,
                       sheet: str,
                       ranges: Dict[str, List[List[Any]]],
                       ctx: Context = None) -> Dict[str, Any]:
    """
    Batch update multiple ranges in a Google Spreadsheet.
    
    Args:
        spreadsheet_id: The ID of the spreadsheet (found in the URL)
        sheet: The name of the sheet
        ranges: Dictionary mapping range strings to 2D arrays of values
               e.g., {'A1:B2': [[1, 2], [3, 4]], 'D1:E2': [['a', 'b'], ['c', 'd']]}
    
    Returns:
        Result of the batch update operation
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    
    # Prepare the batch update request
    data = []
    for range_str, values in ranges.items():
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
    result = sheets_service.values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body=batch_body
    ).execute()
    
    return result


@mcp.tool()
def add_rows(spreadsheet_id: str,
             sheet: str,
             count: int,
             start_row: Optional[int] = None,
             ctx: Context = None) -> Dict[str, Any]:
    """
    Add rows to a sheet in a Google Spreadsheet.
    
    Args:
        spreadsheet_id: The ID of the spreadsheet (found in the URL)
        sheet: The name of the sheet
        count: Number of rows to add
        start_row: 0-based row index to start adding. If not provided, adds at the end.
    
    Returns:
        Result of the operation
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    
    # Get sheet ID
    spreadsheet = sheets_service.get(spreadsheetId=spreadsheet_id).execute()
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
    result = sheets_service.batchUpdate(
        spreadsheetId=spreadsheet_id,
        body=request_body
    ).execute()
    
    return result


@mcp.tool()
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
    spreadsheet = sheets_service.get(spreadsheetId=spreadsheet_id).execute()
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
    result = sheets_service.batchUpdate(
        spreadsheetId=spreadsheet_id,
        body=request_body
    ).execute()
    
    return result


@mcp.tool()
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
    spreadsheet = sheets_service.get(spreadsheetId=spreadsheet_id).execute()
    
    # Extract sheet names
    sheet_names = [sheet['properties']['title'] for sheet in spreadsheet['sheets']]
    
    return sheet_names


@mcp.tool()
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
    src = sheets_service.get(spreadsheetId=src_spreadsheet).execute()
    src_sheet_id = None
    
    for s in src['sheets']:
        if s['properties']['title'] == src_sheet:
            src_sheet_id = s['properties']['sheetId']
            break
            
    if src_sheet_id is None:
        return {"error": f"Source sheet '{src_sheet}' not found"}
    
    # Copy the sheet to destination spreadsheet
    copy_result = sheets_service.sheets().copyTo(
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
        
        rename_result = sheets_service.batchUpdate(
            spreadsheetId=dst_spreadsheet,
            body=rename_request
        ).execute()
        
        return {
            "copy": copy_result,
            "rename": rename_result
        }
    
    return {"copy": copy_result}


@mcp.tool()
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
    spreadsheet_data = sheets_service.get(spreadsheetId=spreadsheet).execute()
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
    result = sheets_service.batchUpdate(
        spreadsheetId=spreadsheet,
        body=request_body
    ).execute()
    
    return result


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
    spreadsheet = sheets_service.get(spreadsheetId=spreadsheet_id).execute()
    
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


@mcp.tool()
def create_spreadsheet(title: str, ctx: Context = None) -> Dict[str, Any]:
    """
    Create a new Google Spreadsheet.
    
    Args:
        title: The title of the new spreadsheet
    
    Returns:
        Information about the newly created spreadsheet including its ID
    """
    sheets_service = ctx.request_context.lifespan_context.sheets_service
    
    # Define the spreadsheet body
    spreadsheet_body = {
        'properties': {
            'title': title
        }
    }
    
    # Create the spreadsheet
    spreadsheet = sheets_service.create(body=spreadsheet_body).execute()
    
    return {
        'spreadsheetId': spreadsheet['spreadsheetId'],
        'title': spreadsheet['properties']['title'],
        'sheets': [sheet['properties']['title'] for sheet in spreadsheet.get('sheets', [])]
    }


@mcp.tool()
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
    result = sheets_service.batchUpdate(
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


def main():
    # Run the server
    mcp.run()