#!/usr/bin/env python3
import requests
import argparse
import json
from datetime import datetime


def get_run_details(run_number, base_url="http://cmslabserver:5000"):
    """Get details for a specific run number."""
    try:
        padded_run = str(run_number)
        response = requests.get(f"{base_url}/test_run/run{padded_run}")
        if response.status_code != 200:
            print(f"Error fetching run details: {response.status_code}")
            return None

        return response.json()

    except requests.RequestException as e:
        print(f"Error connecting to database: {e}")
        return None


def get_session_details(session_name, base_url="http://cmslabserver:5000"):
    """Get detailed information for a specific session."""
    try:
        response = requests.get(f"{base_url}/sessions/{session_name}")
        if response.status_code != 200:
            print(f"Error fetching session details: {response.status_code}")
            return None

        return response.json()

    except requests.RequestException as e:
        print(f"Error fetching session details: {e}")
        return None


def format_run_details(run_data):
    """Format run details for display."""
    output = []
    output.append("=" * 80)
    output.append("RUN DETAILS:")
    output.append("-" * 80)
    output.append(f"Run Name: {run_data.get('test_runName', 'N/A')}")
    output.append(f"Date: {run_data.get('runDate', 'N/A')}")
    output.append(f"Session: {run_data.get('runSession', 'N/A')}")
    output.append(f"Status: {run_data.get('runStatus', 'N/A')}")
    output.append(f"Type: {run_data.get('runType', 'N/A')}")
    output.append(f"Module Tests: {', '.join(run_data.get('moduleTestName', []))}")
    output.append(f"Run File: {run_data.get('runFile', 'N/A')}")

    # Format run configuration if present
    if "runConfiguration" in run_data:
        output.append("\nRun Configuration:")
        config = run_data["runConfiguration"]
        output.append(f"  Events: {config.get('Nevents', 'N/A')}")
        if "boards" in config:
            for board_id, board_data in config["boards"].items():
                output.append(f"  Board {board_id}:")
                output.append(f"    IP: {board_data.get('ip', 'N/A')}")

    output.append("=" * 80)
    return "\n".join(output)


def format_session_details(session):
    """Format session details for display."""
    output = []
    output.append("\nSESSION DETAILS:")
    output.append("-" * 80)
    output.append(f"Session Name: {session.get('sessionName', 'N/A')}")
    output.append(f"Operator: {session.get('operator', 'N/A')}")
    output.append(f"Timestamp: {session.get('timestamp', 'N/A')}")
    output.append(f"Description: {session.get('description', 'N/A')}")
    output.append(f"Modules List: {', '.join(session.get('modulesList', []))}")

    # Add any additional details that might be present
    for key, value in session.items():
        if key not in [
            "sessionName",
            "operator",
            "timestamp",
            "description",
            "modulesList",
        ]:
            output.append(f"{key}: {value}")

    output.append("=" * 80)
    return "\n".join(output)


def update_session_comment(
    session_name, new_comment, base_url="http://cmslabserver:5000"
):
    """Update the description/comment for a specific session."""
    try:
        # Prepare the update data
        update_data = {"description": new_comment}

        # Send PUT request to update the session
        response = requests.put(f"{base_url}/sessions/{session_name}", json=update_data)

        if response.status_code != 200:
            print(f"Error updating session comment: {response.status_code}")
            return False

        return True

    except requests.RequestException as e:
        print(f"Error updating session comment: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Search for run and session details by run number"
    )
    parser.add_argument("run_number", type=str, help="Run number to search for")
    parser.add_argument(
        "--url",
        default="http://cmslabserver:5000",
        help="Base URL for the database API",
    )
    parser.add_argument(
        "--edit-comment",
        nargs="?",
        const=True,
        metavar="COMMENT",
        help="Edit the session comment. If COMMENT is provided, updates directly. If no COMMENT, enters interactive mode",
    )

    args = parser.parse_args()

    # Get run details
    run_data = get_run_details(args.run_number, args.url)

    if not run_data:
        print(f"No run found with number {args.run_number}")
        return

    # Print run details
    print(format_run_details(run_data))

    # Get and display session details if available
    session_name = run_data.get("runSession")
    if session_name:
        session_details = get_session_details(session_name, args.url)
        if session_details:
            print(format_session_details(session_details))

            # Handle comment editing if requested
            if args.edit_comment is not None:
                print(
                    "\nCurrent comment:",
                    session_details.get("description", "No comment"),
                )

                # If comment was provided via command line, use it directly
                if isinstance(args.edit_comment, str):
                    new_comment = args.edit_comment
                else:
                    # Otherwise enter interactive mode
                    new_comment = input(
                        "Enter new comment (press Enter to keep current): "
                    ).strip()

                if new_comment:
                    if update_session_comment(session_name, new_comment, args.url):
                        print("Comment updated successfully!")
                        # Show updated session details
                        updated_session = get_session_details(session_name, args.url)
                        if updated_session:
                            print("\nUpdated session details:")
                            print(format_session_details(updated_session))
                    else:
                        print("Failed to update comment")
        else:
            print(f"\nCould not fetch details for session: {session_name}")
    else:
        print("\nNo session information available for this run")


if __name__ == "__main__":
    main()
