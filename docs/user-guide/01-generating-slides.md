# Generating Slides

This guide walks you through creating AI-generated presentations using Databricks Tellr.

## Overview

The slide generation workflow allows you to:
- Create presentations from natural language prompts
- Pull live data from connected Genie rooms
- Iteratively refine slides through conversation
- Export to PowerPoint, PDF, or HTML

## Prerequisites

- Access to the Databricks Tellr application
- A Genie room with relevant data (optional, for data-driven slides)

## Step-by-Step Instructions

### Step 01: Open the App

Navigate to the application URL. You'll land directly on the slide generator in pre-session mode, ready to start creating.

![Open the app](images/01-generating-slides/01-app-landing.png)

### Step 02: Configure Tools (Optional)

The AgentConfigBar at the top shows your current tools (Genie agents, etc.). You can add data sources before or after generating slides. Without any Genie agents, the agent runs in prompt-only mode.

![AgentConfigBar](images/01-generating-slides/02-generator-view.png)

### Step 03: Enter Your Prompt

Click in the chat input area at the bottom of the screen.

![Chat input](images/01-generating-slides/03-chat-input-empty.png)

### Step 04: Describe Your Presentation

Type a clear, specific prompt describing what you want:
- Topic and scope
- Number of slides (optional)
- Data to include (if using Genie)
- Any specific requirements

![Prompt entered](images/01-generating-slides/04-chat-input-with-prompt.png)

### Step 05: Send Your Request

Click the **Send** button or press Enter to start generation. A session is created automatically on your first message.

![Send button](images/01-generating-slides/05-send-button-enabled.png)

## Iterating on Your Slides

After slides are generated, they appear in the right panel. You can see progress in the chat panel as slides stream in.

Refine slides through follow-up messages in the same session:

| Action | Example Prompt |
|--------|----------------|
| Edit slide contents | "Change title to 'Q4 Results'" |
| Add a slide | "Add a new slide about \{X\} after this one" |
| Regenerate all | "Regenerate all slides with more data" |

## Navigating Slides

Click any thumbnail in the ribbon on the left to jump to that slide. You can also use the arrow buttons on the stage, or keyboard arrow keys when the viewer is focused. The current slide is always kept in view in the ribbon.

To refine a specific slide, navigate to it and describe the change in the chat panel — the AI will target the slide you are currently viewing.

## Review Feedback

Each slide is checked as it lands. Anything the review finds appears in the feedback drawer under the slide, and the slide's thumbnail shows an amber dot until you have seen it.

Each point is explained in plain words, with a note on what happened to it: it was fixed automatically, it was not fixed automatically, or it is a judgement call left to you. Click **Show details** under a point to read the reviewer's technical note, and **Hide details** to fold it away again.

For a point that was not fixed, choose what happens next:

- **Apply** asks the agents to fix it.
- **Dismiss** hides it.
- **Discuss** moves it to the chat so you can talk it through first.

Apply and Discuss send the technical note along with your request so the agents have what they need, but the chat keeps it folded under **Reviewer's details**. Click it to read it.

Points about the deck as a whole, such as a gap in the story, repeated points or a missing conclusion, appear as a chat message instead. The reviewer's specifics are folded underneath, under **Reviewer's details**.

## Returning to a Previous Session

To get back to a previous session, click **My Sessions** in the navigation bar. Any session with slides has a **Restore** button that loads it back into the editor.

## Tips

- **Be specific**: Include topic, audience, and desired outcomes in your prompt
- **Use data queries**: Ask questions about your data, e.g., "Show top 10 customers by revenue"
- **Iterate**: Start simple and refine through follow-up messages
- **Check verification**: Click Verify on slides with data claims to validate accuracy
- **Share your work**: Use the **Share** button to copy a read-only link to your presentation

## Related Guides

- [Saving and Loading Configurations](./02-creating-profiles.md) - Save and reuse configuration snapshots
- [Advanced Configuration](./03-advanced-configuration.md) - Customize prompts and styles
