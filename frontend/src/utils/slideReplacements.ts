export const isContiguous = (indices: number[]): boolean => {
  if (indices.length <= 1) {
    return true;
  }

  const sorted = [...indices].sort((a, b) => a - b);
  for (let i = 1; i < sorted.length; i += 1) {
    if (sorted[i] - sorted[i - 1] !== 1) {
      return false;
    }
  }

  return true;
};
