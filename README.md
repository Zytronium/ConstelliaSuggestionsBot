# Deviant Suggestions Drone

Deviant Suggestions Drone is a Discord bot desgined to replace Constellia's
suggestions bot. It's tailored for Constellia's exact needs, enforcing the
suggestions format and allowing for longer suggestion descriptions.

## Features

### Done
- Suggestion command
  - Allows attaching an image
  - Gives the user a short form to make it easier to format suggestions
- Displays suggestions in a nicely formatted widget with upvote/downvote buttons
  - Automatically pretty formats suggestions into different sections including:
    - Submitter display name and profile picture
    - Title
    - Description
    - Pros
    - Cons
    - Results
    - (if approved/rejected) Approved/rejected and why
    - User ID | Suggestion ID | Timestamp
    - Upvote / downvote buttons
  - Allows users to change or remove their vote
- Persistence across bot reboots so users can still vote on old suggestions
- Sanitization to prevent injection attacks
- Admins can select what channel suggestions get posted in
- Admins can select what role grants the ability to approve/reject a suggestion
- Creates a thread for each suggestion. When a suggestion is approved or
rejected, the thread is locked.
- Choice to Approve/reject anonymously or not (default is false) 
- Admin ability to set a role that revokes the ability to suggest
- Lists the required permissions its missing if it fails to respond due to missing permissions (ephemerally to avoid missing send perms)

### Planned Features
- None

## Known Bugs
- Approving/rejecting suggestions inside their own thread causes the interaction to fail because the thread archives, though the suggestion is successfully approved/rejected.

**Suggestions Channel Bot Permissions Required** if denied to @everyone:
- Send Messages
- Create Public Threads
- Embed Links (for some reason)

## Commands:
