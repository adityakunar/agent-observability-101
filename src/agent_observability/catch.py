"""Catch a claim that the record does not back, while the chat runs.

A claim is a reply that reports a finished business action ("I have swapped your
pizza"). The host believes the record, not the words: when the reply holds an action
word and the business record did not change in the whole turn, the claim is false.

The words only point at a sentence. A refusal such as "I cannot change it once it has
been added" holds one too. So the host does not punish a catch: it gives the model one
more step to act or to correct itself, and warns the customer only if the claim stays.
"""

import re

# Words that report a finished business action. Whole words only: "placed" must not
# match inside "replaced".
CLAIM_WORDS = re.compile(
    r"\b(added|removed|replaced|swapped|updated|changed|cancelled|applied|saved|placed|confirmed)\b",
    re.I,
)

# What the host tells the model after a catch. It goes on a copy of the history, like the
# cue in client.py: the next request carries it, the conversation does not keep it.
CORRECTION = {
    "role": "user",
    "content": (
        "Shop check: your answer says that something changed, but the cart and the orders"
        " are the same as before the customer's last message. No tool changed them. If the"
        " customer asked for a change, make it now with the tools. If not, answer again and"
        " say plainly what was not done."
    ),
}

# What the customer reads when the model claims the same again after the correction.
NOTE = "\n\nShop check: your cart did not change in this turn. Please check it before you order."


def claims(text: str) -> bool:
    """Whether the text reports a finished business action."""
    return bool(CLAIM_WORDS.search(text))
