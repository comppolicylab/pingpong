from .adjectives import adjectives
from .animals import animals
from hashlib import md5
from .compress import compress
import re


def animal_hash(input: str) -> str:
    """
    Generate the anthropomorphic name given some input bytes.
    :param input: The input bytes (strings must be encoded).
    :return: The animal name in angry-purple-tiger format.
    """
    # take the md5 checksum of the input bytes
    hex_digest = md5(input.encode()).hexdigest()

    # split the digest into byte pairs and convert to hex ints
    p = re.compile("(..?)")
    pairs = p.findall(hex_digest)
    bytes = [int(x, base=16) for x in pairs]
    compressed = compress(bytes, 2)

    # use the compressed output as the indices for the adjective-color-animal format
    adjective = adjectives[compressed[0]]
    animal = animals[compressed[1]]

    return f"{adjective.capitalize()} {animal.capitalize()}"
