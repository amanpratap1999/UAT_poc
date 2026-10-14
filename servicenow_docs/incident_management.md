# ServiceNow Incident Management Reference

## Overview

Incident Management is a core ITSM process in ServiceNow that restores normal service operation as quickly as possible while minimizing impact on business operations.

## Incident Lifecycle States

An incident progresses through these states:

| State | Value | Description |
|-------|-------|-------------|
| New | 1 | Initial state when an incident is created |
| In Progress | 2 | Work has begun on the incident |
| On Hold | 3 | Work is paused, awaiting external input |
| Resolved | 6 | The issue has been resolved |
| Closed | 7 | Incident is closed after resolution verification |
| Canceled | 8 | Incident was canceled (not applicable) |

## State Transitions

Valid state transitions:
- New → In Progress (requires Assignment Group)
- New → Canceled
- In Progress → On Hold (requires On Hold Reason)
- In Progress → Resolved (requires Resolution Code, Resolution Notes)
- On Hold → In Progress
- Resolved → In Progress (reopen)
- Resolved → Closed
- Closed → In Progress (reopen — requires justification)

## Key Form Fields

### Required Fields (Always)
- **Short Description**: Brief summary of the incident
- **Caller**: The person reporting the incident

### Required for State Transitions
- **Assignment Group**: Required to move to "In Progress"
- **Assigned To**: Recommended when moving to "In Progress"
- **On Hold Reason**: Required when moving to "On Hold"
- **Resolution Code**: Required when resolving
- **Resolution Notes**: Required when resolving

### Standard Fields
- **Category**: Classification category
- **Subcategory**: Sub-classification
- **Impact**: Business impact (1-High, 2-Medium, 3-Low)
- **Urgency**: How quickly the issue needs resolution (1-High, 2-Medium, 3-Low)
- **Priority**: Calculated from Impact × Urgency (1-Critical, 2-High, 3-Moderate, 4-Low, 5-Planning)
- **Description**: Detailed description of the incident
- **Configuration Item**: Affected CI
- **Contact Type**: How the incident was reported

## Priority Matrix

| | Impact: High (1) | Impact: Medium (2) | Impact: Low (3) |
|----------|------------------|--------------------|--------------------|
| **Urgency: High (1)** | 1 - Critical | 2 - High | 3 - Moderate |
| **Urgency: Medium (2)** | 2 - High | 3 - Moderate | 4 - Low |
| **Urgency: Low (3)** | 3 - Moderate | 4 - Low | 5 - Planning |

## Work Notes and Activity

- **Work Notes**: Internal notes visible only to IT staff
- **Additional Comments**: Customer-visible notes
- **Activity Log**: Chronological record of all changes

When adding work notes:
1. Navigate to the "Notes" tab or "Work Notes" field
2. Enter the note text
3. Click "Update" or "Save" to record the note
4. The activity log should show the new entry

## Form Sections

Standard incident form sections:
1. **Header**: Number, State, Priority indicators
2. **Details**: Caller, Category, Subcategory, Short Description, Description
3. **Assignment**: Assignment Group, Assigned To
4. **Impact Assessment**: Impact, Urgency, Priority
5. **Resolution**: Resolution Code, Resolution Notes (visible when resolving)
6. **Related Records**: Related incidents, problems, changes
7. **Notes**: Work Notes, Additional Comments, Activity Log

## Common UI Patterns

### Creating a New Incident
1. Navigate to Incident → Create New
2. Fill required fields (Caller, Short Description)
3. Set Category, Impact, Urgency
4. Click "Submit" to create

### Updating an Incident
1. Open the incident from the list
2. Modify fields as needed
3. Click "Update" to save changes

### Resolving an Incident
1. Open the incident
2. Set State to "Resolved"
3. Fill Resolution Code (e.g., "Solved (Permanently)")
4. Fill Resolution Notes with explanation
5. Click "Update"

### Closing an Incident
1. Open a resolved incident
2. Set State to "Closed"
3. Click "Update"

## Validation Rules

- Cannot resolve without Resolution Code and Resolution Notes
- Cannot put on hold without On Hold Reason
- Cannot move to In Progress without Assignment Group
- Short Description is always mandatory
- Caller is always mandatory for new incidents
- Priority is auto-calculated and typically read-only
