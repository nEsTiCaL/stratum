export const MAX = 10;
let counter = 0;

export function greet(name) {
  return name;
}

function _helper() {
  return 1;
}

const add = (a, b) => a + b;

export class Widget {
  static kind = "w";
  #secret = 1;

  constructor(id) {
    this.id = id;
  }

  render() {
    return this.id;
  }

  #hidden() {
    return this.#secret;
  }
}
