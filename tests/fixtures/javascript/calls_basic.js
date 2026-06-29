function helper() {
  return 1;
}

function top() {
  helper();
  log(1);
}

class C {
  a() {
    return this.b();
  }

  b() {
    return helper();
  }
}

helper();
