import 'dart:io';

void main() {
  // VIOLATION: blocking sleep on UI isolate
  sleep(5);
  print('App started');
}
