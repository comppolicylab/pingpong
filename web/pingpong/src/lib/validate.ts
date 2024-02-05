export const invalid = (field: string, message: string) => {
  return {
    $status: 400,
    field,
    detail: message
  };
};
