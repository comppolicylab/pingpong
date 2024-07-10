from math import floor
from functools import reduce
from typing import List


def compress(bytes: List[int], target: int = 2) -> List[int]:
    """
    Compress a list of ints into (usually) 2 indices.
    :param bytes: The list of input ints.
    :param target: The size of the compressed output (default: 2).
    :return: The list of indices of the target length.
    """
    length = len(bytes)
    if target > length:
        raise ValueError('Fewer input bytes than requested output')

    # split the input list into target number of sublists
    seg_size = floor(length / target)
    segments = []
    for i in range(0, seg_size * target, seg_size):
        segments.append(bytes[i:i+seg_size])

    # ensure that any overflow goes into the last segment
    last_seg = segments[len(segments) - 1]
    segments[len(segments) - 1] = last_seg + bytes[target * seg_size:]

    # XOR filter to generate the indices
    checksums = [reduce(lambda acc, curr: acc ^ curr, s) for s in segments]

    return checksums