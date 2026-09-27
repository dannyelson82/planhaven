"""A minimal plugin: counts completed tasks per project in its own plugin data."""

from planhaven_sdk import Event, PluginContext, Registry

SEEN: list[str] = []


async def on_task_completed(ctx: PluginContext, event: Event) -> None:
    if event.project_id is None:
        return
    current = await ctx.get_data("project", event.project_id, "completed") or 0
    await ctx.put_data("project", event.project_id, "completed", current + 1)
    SEEN.append(event.type)


def register(registry: Registry) -> None:
    registry.on_event("task.completed", on_task_completed)
