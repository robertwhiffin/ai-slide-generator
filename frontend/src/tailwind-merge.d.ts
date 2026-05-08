declare module "tailwind-merge" {
  export function twMerge(...classLists: (string | undefined | null | false)[]): string;
}
