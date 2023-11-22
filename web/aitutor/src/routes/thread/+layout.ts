export function load({ params }: { params: { slug: string } }) {
  return {
    currentThread: params.slug,
    threads: [{
      id: '1',
      title: 'Thread 1',
      lastMessage: "Hello",
    }, {
      id: '2',
      title: 'Thread 2',
      lastMessage: "World",
    }],
  };
}
