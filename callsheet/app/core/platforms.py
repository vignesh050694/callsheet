"""The platforms this product listens to (E03-S07).

A short, closed vocabulary that everything above the collection layer speaks: the port
takes a `Platform`, mentions are stored against one, and dashboards group by one. It is
deliberately *not* the vendor's word for the platform, and it never encodes who fetched
the data — swapping the provider behind X must not change what a mention says it is.
"""

import enum


class Platform(enum.StrEnum):
    X = "x"
    INSTAGRAM = "instagram"
    REDDIT = "reddit"
    YOUTUBE = "youtube"
