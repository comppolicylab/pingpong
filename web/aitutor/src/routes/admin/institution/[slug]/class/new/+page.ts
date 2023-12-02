export async function load({ params }) {
  return {
    institution_id: params.slug,
  }
}
