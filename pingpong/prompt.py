import re
import logging

from .hash import hash_id
from .schemas import PromptRandomBlock, PromptRandomOption

logger = logging.getLogger(__name__)


def replace_random_blocks(prompt: str, thread_id: str) -> str:
    random_pattern = re.compile(r"<random\b([^>]*)>(.*?)</random>", re.DOTALL)
    option_pattern = re.compile(
        r'<option(?:\s+weight="(\d+)")?>(.*?)</option>', re.DOTALL
    )

    replacements = []
    new_prompt = prompt
    for random_match in random_pattern.finditer(prompt):
        random_attrs = random_match.group(1)
        inner_content = random_match.group(2)

        # Parse attributes of <random>
        count_match = re.search(r'count="(\d+)"', random_attrs)
        repeat_match = re.search(r'allow-repeat="(true|false)"', random_attrs)

        count = int(count_match.group(1)) if count_match else 1
        allow_repeat = (
            repeat_match.group(1).lower() == "true" if repeat_match else False
        )

        # Parse <option> elements
        options = []
        for opt_match in option_pattern.finditer(inner_content):
            weight = int(opt_match.group(1)) if opt_match.group(1) else 1
            text = opt_match.group(2).strip()
            options.append(PromptRandomOption(text=text, weight=weight))

        block = PromptRandomBlock(
            options=options, count=count, allow_repeat=allow_repeat
        )

        if not options:
            logger.warning(
                f"No options found in <random> block in thread {thread_id}. Skipping replacement."
            )
            continue

        chosen = pick_options(block, thread_id)

        if not chosen:
            logger.error(
                f"No options were chosen for <random> block in thread {thread_id}. Skipping replacement."
            )
            continue
        replacements.append(
            (
                random_match.start(),
                random_match.end(),
                "\n".join([option.text for option in chosen]),
            )
        )

    # Replace the <random> blocks with the chosen options
    for start, end, options_text in reversed(replacements):
        new_prompt = new_prompt[:start] + options_text + new_prompt[end:]

    return new_prompt


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
        u = hash_id(f"{seed}_{i}") * total_w

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
        u = hash_id(f"{seed}_{option.text}") or 1e-16
        key = u ** (1.0 / option.weight)
        priority_list.append((key, option))

    priority_list.sort(key=lambda kv: kv[0], reverse=True)
    top_options = priority_list[: min(block.count, len(priority_list))]
    return [option for _, option in top_options]
