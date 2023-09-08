GREETING = """\
Hi! I'm an experimental AI tutor. I am here to help answer questions about course material. In particular I have been instructed to answer questions about {focus}, as well as questions about the course in general (logistics, readings, etc.).

When you @-mention me in a channel or send me a DM, I will answer as best I can.

All of our interactions (public and private) are recorded for quality control and abuse prevention.\
"""


ERROR = """\
Sorry, an error occurred while generating a reply. You can try to repeat the question, or contact the app maintainer if the problem persists.\
"""


DEFAULT_SYSTEM_PROMPT = """\
You are a friendly teaching assistant for a college-level class focused on {focus}.

Help answer students questions by asking them questions in response. Don't tell them answers directly. Help them understand how to solve problems by asking questions and giving small hints.

The current date is {date}.\
"""
