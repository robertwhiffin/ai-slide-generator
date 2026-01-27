# Creating Profiles

This guide explains how to create and manage configuration profiles in Databricks Tellr.

## Overview

Profiles bundle together:
- **Genie Room** - Your data source for queries
- **Slide Style** - CSS styling for generated slides
- **Deck Prompt** - Template that guides slide structure

Creating profiles for different use cases (e.g., "Quarterly Reviews", "Customer Presentations") allows you to quickly switch contexts.

## Prerequisites

- Access to Databricks Tellr
- Knowledge of available Genie rooms in your workspace
- (Optional) Custom slide styles or deck prompts

## Step-by-Step Instructions

### Step 01: Navigate to Profiles

Click "Profiles" in the navigation bar to open the profile management page.
The page displays all available profiles with their descriptions and settings.

![Profiles page](images/02-creating-profiles/01-profiles-page.png)



### Step 02: Create New Profile

Click the "+ Create Profile" button to start the creation wizard.

![Create Profile button](images/02-creating-profiles/03-create-profile-button.png)

### Step 03: Enter Basic Information

In Step 1 of the wizard, enter:
- **Name** - A unique, descriptive name (required)
- **Description** - What this profile is used for (optional)

![Wizard Step 1](images/02-creating-profiles/04-wizard-step1-basics.png)

Fill in both fields with clear, descriptive text.

![Wizard Step 1 Filled](images/02-creating-profiles/05-wizard-step1-filled.png)

### Step 04: Genie Space (Optional)

Genie Space is optional. Skip to create a prompt-only profile, or connect a Genie room for data queries.

![Genie Space Step](images/02-creating-profiles/06-wizard-step2-genie.png)

### Step 05: Select Slide Style (Required)

Choose a slide style that matches your presentation needs. This is required to proceed.

![Style Selection](images/02-creating-profiles/07-wizard-step3-style.png)

Select a style to define the visual appearance of your slides.

![Style Selected](images/02-creating-profiles/08-wizard-step3-style-selected.png)

### Step 06: Deck Prompt (Optional)

Optionally select a deck prompt template to guide slide structure.

![Prompt Selection](images/02-creating-profiles/09-wizard-step4-prompt.png)

### Step 07: Review & Create

Review your settings and click "Create Profile" to finish.

![Review Step](images/02-creating-profiles/10-wizard-step5-review.png)

## Editing Profiles

### Open Profile Details

Click on any profile card to view its details.

![Profile card](images/02-creating-profiles/12-profile-card.png)

### View Details

The detail view shows all profile settings.

![Profile details](images/02-creating-profiles/13-profile-details.png)

### Edit Profile

Click the Edit button to modify settings.

![Edit button](images/02-creating-profiles/14-profile-edit-button.png)

## Profile Settings Reference

| Setting | Description | Can Change After Creation |
|---------|-------------|---------------------------|
| Name | Profile identifier | Yes |
| Description | Usage notes | Yes |
| Genie Room | Data source | Yes |
| Slide Style | Visual styling | Yes |
| Deck Prompt | Generation template | Yes |
| Default | Whether this loads on startup | Yes |

## Tips

- **Use descriptive names**: "Q4 Customer Review" is better than "Profile 1"
- **Match prompts to use case**: Different deck prompts suit different presentation types
- **Test with sample prompts**: After creating a profile, generate a test presentation
- **One profile per workflow**: Create separate profiles for different reporting needs

## Related Guides

- [Generating Slides](./01-generating-slides.md) - Use your profile to create presentations
- [Advanced Configuration](./03-advanced-configuration.md) - Create custom prompts and styles
