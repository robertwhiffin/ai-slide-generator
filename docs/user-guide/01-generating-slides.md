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

## Clearing the Chat

A long conversation can drift. To start the conversation over without losing your deck, click **Clear chat** at the top of the chat panel, on the right of the "AI Assistant" heading.

A confirmation asks "Clear chat?" before anything happens. Confirm with **Clear chat**, or choose **Cancel** to leave everything as it is.

**What is kept:**
- Your slides
- The deck's Spec (the **Spec** view beside **Slides**)
- Your save points
- The Graph Version the deck is pinned to (the "Pinned Graph Version" line above the chat). Clearing the chat does not move the deck to a newer version.

**What is deleted:** your conversation on this deck. The chat panel empties, and stays empty after you reload the page.

The assistant carries on from the Spec and the current slides, not from the old conversation. You can send "make slide 3 shorter" straight away.

**When the button is available:**
- Only on decks that have a Spec, and only when you can edit the deck. Viewers do not see it. See [Sharing & Permissions](./08-profile-sharing-permissions.md).
- It is greyed out while a reply is being generated, while you are previewing a save point, while the chat input is read-only, and when the chat is already empty.
- It clears **your** conversation only. On a shared deck, each person's conversation is their own, and clearing yours never touches anyone else's.
- If something else is still running on the deck, such as a slide operation or a reply in another tab, you see "Something is still running on this deck. Wait for it to finish, then clear the chat." Your conversation is kept; try again once it finishes.

**Things to know:**
- **It cannot be undone.** The cleared messages do not come back to the chat.
- **Save points keep the chat they were saved with.** Previewing an older save point still shows the conversation as it was then. Restoring a save point does not bring a cleared conversation back.
- If the **Clear chat** button is missing right after you restore a save point, reload the page and it will reappear.

## Navigating Slides

Click any thumbnail in the ribbon on the left to jump to that slide. You can also use the arrow buttons on the stage, or keyboard arrow keys when the viewer is focused. The current slide is always kept in view in the ribbon.

To refine a specific slide, navigate to it and describe the change in the chat panel — the AI will target the slide you are currently viewing.

## Returning to a Previous Session

To get back to a previous session, click **My Sessions** in the navigation bar. Any session with slides has a **Restore** button that loads it back into the editor.

## Reviewing the Deck Spec

Click **Spec** above the slide viewer to see the plan the agents work from.

It is read-only; click **Discuss** to change it in the chat.

Click **Export spec** to download it as a Markdown file, for review or sharing outside Tellr. The file is named after the title the agents gave the plan, which can differ from the deck name in the header. It holds everything in the Spec view, plus that title, each slide's type and data references, and the data the agents resolved: a summary, each figure with its source, and any gaps they recorded.

## Tips

- **Be specific**: Include topic, audience, and desired outcomes in your prompt
- **Use data queries**: Ask questions about your data, e.g., "Show top 10 customers by revenue"
- **Iterate**: Start simple and refine through follow-up messages
- **Check verification**: Click Verify on slides with data claims to validate accuracy
- **Share your work**: Use the **Share** button to copy a read-only link to your presentation

## Related Guides

- [Saving and Loading Configurations](./02-creating-profiles.md) - Save and reuse configuration snapshots
- [Advanced Configuration](./03-advanced-configuration.md) - Customize prompts and styles
