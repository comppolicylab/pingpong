import asyncio

from azure.communication.email import EmailClient

from .base import EmailSender


class AzureEmailSender(EmailSender):
    def __init__(self, from_address: str, conn_str: str):
        self.client = EmailClient.from_connection_string(conn_str)
        self.from_address = from_address

    async def send(self, to: str, subject: str, message: str):
        azure_msg = {
            "senderAddress": self.from_address,
            "recipients": {
                "to": [{"address": to}],
            },
            "content": {
                "subject": subject,
                "plainText": message,
            },
        }
        poller = self.client.begin_send(azure_msg)

        # Create a future for the polling loop
        send_future = asyncio.get_running_loop().create_future()
        poller.add_done_callback(send_future.set_result)

        # Wait for the send operation to complete
        await send_future
        result = poller.result()
        if result["error"]:
            raise Exception('Failed to send email: {result["error"]}')
