# AI apps (Claude and others)

Connect an AI app such as Claude to PlanHaven. It can then read your projects, answer questions
about them and help you plan: "what's left on the boat?", "make a parts list for the brake job".
If you allow it, it can also work on your projects with you: add, change and delete tasks,
notes, lists, quotes, costs, contacts, assets and their services, and share a project or asset
with people in your household.

You choose what each app may do:

- **Read only**: it reads and searches your projects. It can't change anything.
- **Suggest changes**: it can also suggest changes. Nothing happens until you approve each one.
- **Make changes**: changes happen straight away, and you can undo each one.

Anything an AI app deletes goes to the **Trash**, so you can bring it back for 30 days, and
every change it makes can be undone. It sees every project you can see, except projects marked
**Local AI only**. Only connect apps you trust.

An AI app can never make share links, change who owns something, change your own access, change
your account or security settings, empty the Trash, or upload or download files.

## Connect Claude

You need the address of your PlanHaven, for example `https://planhaven.example.com`.

**On a computer (claude.ai or the Claude app)**
1. In Claude, open **Settings**, then **Connectors**.
2. Click **Add custom connector**.
3. Name it **PlanHaven**. In the address box, type your PlanHaven address followed by `/mcp`,
   for example `https://planhaven.example.com/mcp`. Click **Add**.
4. Click **Connect**. PlanHaven opens; sign in if it asks.
5. Choose what Claude may do, then click **Allow**. Confirm it's you with your second factor.
6. You're back in Claude. In a chat, turn PlanHaven on under the tools (search and tools) button.

**On a phone**: add the connector on a computer first (steps above). It then works in the Claude
app on your phone too.

Other AI apps that support "MCP" connectors work the same way: give them the `/mcp` address.

![Connecting an AI app](screens/desktop/ai-connect.jpg)

## Approve suggested changes

When an app set to **Suggest changes** wants to change something, you get a notification.

1. Open **AI** (in the menu on a computer; on a phone, tap the notification, or open **Account**
   and tap **AI suggestions and changes**).
2. Under **Waiting for your approval**, read each change.
3. Tap **Approve** or **Decline**. **Approve all** does them all at once.

If something changed since the suggestion was made (the task was deleted, say), approving it
sets it aside instead. Approving a sharing change asks for your second factor.

![The AI page](screens/desktop/ai.jpg)

## Undo an AI change

Under **Recent AI changes** on the **AI** page, tap **Undo** next to a change.

- Something it **added** is moved to the Trash.
- Something it **changed** goes back to how it was.
- Something it **deleted** comes back from the Trash. A deleted reading is added again.
- Someone it **shared** with gets their old access back (or loses it again). PlanHaven asks
  for your second factor first, as it does whenever sharing changes.

If Undo can't work any more (you already restored the thing from the Trash, say), the page tells
you so.

## Change or disconnect an app

1. Open **Account**, then go to **Connected AI apps**.
2. Pick a different choice under the app's name to change what it may do. Allowing more
   (changes, or making changes without asking) asks for your second factor.
3. Tap **Disconnect** to stop it at once. To use it again, connect it again from the app.

![Connected AI apps in Account](screens/desktop/ai-apps.jpg)

## Keep a project away from AI apps

The project's owner can open it, scroll to the bottom and tick **Local AI only**. AI apps then
can't see it at all.

## Good to know

- Each person connects their own apps. An app sees only what that person can see, and can only
  change what that person can change.
- Text in your projects is shown to the app as your content, not as instructions to it.
- Claude asks you in the chat before deleting something, unless you asked it to.
- For people building with AI apps: the **planhaven_connection_info** tool says what a
  connection may do, and errors say why a change failed and what to try instead.
- Choose when you're told about suggestions in **Account**, under **Notifications** ("AI apps").
