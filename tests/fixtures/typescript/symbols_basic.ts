export interface Shape {
  area(): number;
  name: string;
}

export type ID = string | number;

export enum Color {
  Red,
  Green,
}

export class Box {
  private secret = 1;
  size = 0;

  private compute(): number {
    return this.secret;
  }

  area(): number {
    return this.size;
  }
}

namespace Geo {
  export const PI = 3;
}
