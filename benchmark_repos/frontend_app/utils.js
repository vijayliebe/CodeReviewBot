export function validateEmail(email) {
  // VIOLATION: Using non-strict equality (Rule: strict-equality)
  if (email == null || email == "") {
    return false;
  }
  return email.includes("@");
}
