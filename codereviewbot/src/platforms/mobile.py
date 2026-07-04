from pathlib import Path

from src.platforms._shared import JAVASCRIPT_RULES, _deps_contain, _file_contains
from src.platforms.base import PlatformAdapter

MOBILE_RULES = [
    {
        "id": "mobile-main-thread-block",
        "description": "Never execute blocking network, disk, or heavy computation on the main thread.",
        "pattern": r"(DispatchQueue\.main\.sync|Thread\.sleep|runBlocking|sleep\(\s*\d+)",
        "files": ["**/*.swift", "**/*.kt", "**/*.dart", "**/*.ts", "**/*.tsx", "**/*.java"],
        "severity": "critical",
        "suggestion": "Use background queues, Dispatchers.IO, isolates, or async/await off the UI thread.",
    },
    {
        "id": "mobile-permissions-check",
        "description": "Verify runtime permission handling before location/contacts/media access.",
        "pattern": r"(locationManager|requestPermissions|Geolocator|CLLocationManager|checkSelfPermission)",
        "files": ["**/*.swift", "**/*.kt", "**/*.dart"],
        "severity": "high",
        "suggestion": "Check authorizationStatus and handle denied/permanent-denied states.",
    },
    {
        "id": "mobile-hardcoded-api-key",
        "description": "Do not hardcode API keys in mobile source; use secure storage or env config.",
        "pattern": r'(api[_-]?key|apiKey|API_KEY)\s*[=:]\s*["\'][A-Za-z0-9_\-]{16,}["\']',
        "files": ["**/*.swift", "**/*.kt", "**/*.dart", "**/*.ts", "**/*.tsx"],
        "severity": "critical",
        "suggestion": "Use Keychain, EncryptedSharedPreferences, flutter_dotenv, or react-native-config.",
    },
    {
        "id": "rn-async-storage-secrets",
        "description": "Do not store sensitive tokens in AsyncStorage (React Native).",
        "pattern": r"AsyncStorage\.setItem\([^)]*(token|secret|password|apiKey)",
        "files": ["**/*.ts", "**/*.tsx", "**/*.js"],
        "severity": "high",
        "suggestion": "Use react-native-keychain or expo-secure-store for credentials.",
    },
]


def detect_mobile(root: Path) -> bool:
    if _deps_contain(root, "react-native", "flutter"):
        return True
    if _file_contains(root, "pubspec.yaml", lambda t: "flutter:" in t):
        return True
    if _file_contains(root, "AndroidManifest.xml"):
        return True
    if _file_contains(root, "*.xcodeproj"):
        return True
    if _file_contains(root, "Podfile"):
        return True
    return any(
        _file_contains(root, ext)
        for ext in ("*.swift", "*.kt", "*.dart")
    )


ADAPTER = PlatformAdapter(
    id="mobile",
    name="Mobile (iOS, Android, Flutter, React Native)",
    rules=JAVASCRIPT_RULES + MOBILE_RULES,
    detect=detect_mobile,
    languages=["swift", "kotlin", "dart", "javascript", "typescript"],
    frameworks=["flutter", "react-native", "ios", "android", "swiftui"],
    agent_hints=(
        "Mobile stack: main-thread blocking, permission flows, Keychain/secure storage vs UserDefaults/AsyncStorage, "
        "platform channel / native module contract breaks, ATS (iOS), exported Android components."
    ),
)
