function helper(): number {
  return 1;
}

function top(): void {
  helper();
  log(1);
}

class C {
  a(): number {
    return this.b();
  }

  b(): number {
    return helper();
  }
}

helper();
