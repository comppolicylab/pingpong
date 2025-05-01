import logging

from bs4 import BeautifulSoup, NavigableString

from .hash import hash_id
from .schemas import PromptRandomBlock, PromptRandomOption

logger = logging.getLogger(__name__)


def replace_random_blocks(prompt: str, thread_id: str) -> str:
    soup = BeautifulSoup(prompt, "html.parser")

    level = 0

    while True:
        all_randoms = soup.find_all("random")

        if not all_randoms:
            break

        level += 1
        leaves = [tag for tag in all_randoms if not tag.find("random")]

        for index, tag in enumerate(leaves):
            attrs = tag.attrs
            try:
                count = int(attrs.get("count", 1))
            except ValueError:
                count = 1
            allow_repeat = str(attrs.get("allow-repeat", "")).lower() == "true"
            block_id = attrs.get("id", "")

            options = []
            for opt in tag.find_all("option", recursive=False):
                try:
                    weight = int(opt.get("weight", 1))
                except ValueError:
                    weight = 1
                text = opt.get_text(strip=True)
                options.append(PromptRandomOption(text=text, weight=weight))

            if not options:
                logger.warning(
                    f"No options found in <random> block in thread {thread_id}. Skipping replacement."
                )
                continue

            print(f"Block ID: {block_id or f'{level}_{index + 1}'}")
            block = PromptRandomBlock(
                options=options,
                count=count,
                allow_repeat=allow_repeat,
                id=block_id or f"{level}_{index + 1}",
            )

            chosen = pick_options(block, thread_id)

            if not chosen:
                logger.error(
                    f"No options chosen for <random> block in thread {thread_id}; skipping."
                )
                tag.decompose()
                continue

            replacement_text = "\n".join(opt.text for opt in chosen)

            tag.replace_with(NavigableString(replacement_text))

    return str(soup)


def pick_options(block: PromptRandomBlock, thread_id: str) -> list[PromptRandomOption]:
    """
    Pick options from a PromptRandomBlock based on its configuration.
    If allow_repeat is True, picks with replacement; otherwise, picks without replacement.
    """
    if block.allow_repeat:
        return _pick_with_replacement(thread_id, block)
    else:
        return _pick_without_replacement(thread_id, block)


def _pick_with_replacement(
    seed: str, block: PromptRandomBlock
) -> list[PromptRandomOption]:
    """
    Deterministically draw `block.count` items *with* replacement.
    Similar to inverse transform sampling.
    """
    picks: list[PromptRandomOption] = []
    total_w = block.total_weight
    for i in range(block.count):
        # Generate a unique seed for each selection
        u = hash_id(f"{seed}_{block.id}_{i}") * total_w

        cumulative_weight = 0.0
        for option in block.options:
            cumulative_weight += option.weight
            if u < cumulative_weight:
                picks.append(option)
                break

    return picks


def _pick_without_replacement(
    seed: str, block: PromptRandomBlock
) -> list[PromptRandomOption]:
    """
    Deterministically draw `block.count` items *without* replacement.
    Similar to priority sampling.
    """
    priority_list = []
    for option in block.options:
        u = hash_id(f"{seed}_{block.id}_{option.text}") or 1e-16
        key = u ** (1.0 / option.weight)
        priority_list.append((key, option))

    priority_list.sort(key=lambda kv: kv[0], reverse=True)
    top_options = priority_list[: min(block.count, len(priority_list))]
    return [option for _, option in top_options]
