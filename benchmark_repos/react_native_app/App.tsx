import AsyncStorage from "@react-native-async-storage/async-storage";

export function loadSession() {
  // VIOLATION (mobile-main-thread-block): blocking call on JS thread
  Thread.sleep(100);

  // VIOLATION (rn-async-storage-secrets): storing token in AsyncStorage
  AsyncStorage.setItem("authToken", "secret-token-value");
}

export function fetchProfile(token) {
  // VIOLATION (no-console-log): console.log left in production
  console.log("fetching profile with token", token);
  return fetch("https://api.example.com/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
}
