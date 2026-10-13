"""Repair captions without regenerating audio or changing learning-check IDs.

Preview the affected lecture using the target environment's CONFIG_PATH:
    uv run python -m scripts.repair_lecture_slide_captions --assistant-id 4010 --language ja

Add --apply to realign its existing audio with ElevenLabs and replace captions.
This makes paid forced-alignment requests. Old caption artifacts are retained.
"""

import asyncio

import click

from pingpong import models
from pingpong.config import config
from pingpong.lecture_slide_caption_repair import repair_lecture_slide_captions


@click.command()
@click.option("--deck-id", type=click.IntRange(min=1))
@click.option("--assistant-id", type=click.IntRange(min=1))
@click.option("--language", default="original", show_default=True)
@click.option(
    "--apply",
    is_flag=True,
    help="Write repaired captions; makes paid ElevenLabs forced-alignment requests.",
)
def main(
    deck_id: int | None, assistant_id: int | None, language: str, apply: bool
) -> None:
    if (deck_id is None) == (assistant_id is None):
        raise click.UsageError("Specify exactly one of --deck-id or --assistant-id.")

    async def run() -> int:
        target_deck_id = deck_id
        if assistant_id is not None:
            async with config.db.driver.async_session() as session:
                assistant = await session.get(models.Assistant, assistant_id)
                if assistant is None or assistant.lecture_slide_deck_id is None:
                    raise click.ClickException("Assistant has no lecture slide deck.")
                target_deck_id = assistant.lecture_slide_deck_id
        assert target_deck_id is not None
        return await repair_lecture_slide_captions(
            target_deck_id, language, apply=apply
        )

    try:
        count = asyncio.run(run())
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"{'Repaired' if apply else 'Would repair'} {count} narrated pages.")


if __name__ == "__main__":
    main()
