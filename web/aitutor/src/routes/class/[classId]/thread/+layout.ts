export function load({ params }: { params: { threadId?: string } }) {
  return {
    currentThread: params.threadId ? parseInt(params.threadId, 10) : null,
  };
}
