import logging

from bs4 import BeautifulSoup

from .hash import hash_id
from .schemas import PromptRandomBlock, PromptRandomOption

logger = logging.getLogger("prompt_randomizer")


def replace_random_blocks(prompt: str, thread_id: str, user_id: int) -> str:
    soup = BeautifulSoup(prompt, "html.parser")

    level = 0

    while True:
        all_randoms = soup.find_all("random")

        if not all_randoms:
            break

        level += 1

        if level > 10:
            logger.warning(
                f"Too many nested <random> blocks in thread {thread_id}. Skipping replacements."
            )
            break

        roots = [tag for tag in all_randoms if tag.find_parent("random") is None]

        for block_index, tag in enumerate(roots):
            attrs = tag.attrs
            try:
                count = int(attrs.get("count", 1))
            except ValueError:
                count = 1
            allow_repeat = str(attrs.get("allow-repeat", "")).lower() == "true"
            block_id = attrs.get("id", f"{level}_{block_index + 1}")
            scope = attrs.get("scope", "thread")
            sep = attrs.get("sep", "\n")
            if scope not in {"thread", "user"}:
                logger.warning(
                    f"Invalid scope '{scope}' in <random> block in thread {thread_id}. Using thread_id."
                )
                scope = "thread"

            options = []
            for opt_index, opt in enumerate(tag.find_all("option", recursive=False)):
                try:
                    weight = float(opt.get("weight", 1.0))
                    if weight < 0:
                        logger.warning(
                            f"Invalid weight '{opt.get('weight')}' in <option> tag in thread {thread_id}. Using 1.0."
                        )
                        weight = 1.0
                except ValueError:
                    weight = 1.0
                text = opt.decode_contents(formatter=None)
                option_id = opt.get("id", str(opt_index + 1))
                options.append(
                    PromptRandomOption(id=option_id, text=text, weight=weight)
                )

            if not options:
                logger.warning(
                    f"No options found in <random> block in thread {thread_id}. Skipping replacement."
                )
                continue

            block = PromptRandomBlock(
                seed=f"user_{user_id}" if scope == "user" else thread_id,
                options=options,
                count=count,
                allow_repeat=allow_repeat,
                id=block_id,
                sep=sep,
            )

            logger.debug(f"Processing <random> block in thread {thread_id}: {block}")

            chosen = pick_options(block)

            if not chosen:
                logger.error(
                    f"No options chosen for <random> block in thread {thread_id}; skipping."
                )
                tag.decompose()
                continue

            replacement_text = f"{block.sep}".join(opt.text for opt in chosen)
            fragment = BeautifulSoup(replacement_text, "html.parser")
            tag.replace_with(*fragment.contents)

    return str(soup)


def pick_options(block: PromptRandomBlock) -> list[PromptRandomOption]:
    """
    Pick options from a PromptRandomBlock based on its configuration.
    If allow_repeat is True, picks with replacement; otherwise, picks without replacement.
    """
    if block.allow_repeat:
        return _pick_with_replacement(block)
    else:
        return _pick_without_replacement(block)


def _pick_with_replacement(block: PromptRandomBlock) -> list[PromptRandomOption]:
    """
    Deterministically draw `block.count` items *with* replacement.
    Similar to priority sampling.
    """
    picks: list[PromptRandomOption] = []
    for pick_index in range(block.count):
        best_score = -1.0
        best_option: PromptRandomOption | None = None

        for option in block.options:
            u = hash_id(f"{block.seed}_{block.id}_{option.id}_{pick_index}") or 1e-16
            score = u ** (1.0 / option.weight)

            if score > best_score:
                best_score = score
                best_option = option

        if best_option is not None:
            picks.append(best_option)

    return picks


def _pick_without_replacement(block: PromptRandomBlock) -> list[PromptRandomOption]:
    """
    Deterministically draw `block.count` items *without* replacement.
    Similar to priority sampling.
    """
    priority_list = []
    for option in block.options:
        u = hash_id(f"{block.seed}_{block.id}_{option.id}") or 1e-16
        key = u ** (1.0 / option.weight)
        priority_list.append((key, option))

    priority_list.sort(key=lambda kv: kv[0], reverse=True)
    top_options = priority_list[: min(block.count, len(priority_list))]
    return [option for _, option in top_options]
