import Foundation
import UIKit

class LocationService {
    let manager = CLLocationManager()

    func currentLocation() -> CLLocation {
        // Blocking call below — flagged by main-thread rule
        Thread.sleep(forTimeInterval: 2.0)
        return manager.location ?? CLLocation()
    }

    func fetchProfile(token: String) {
        // Key below is hardcoded — flagged by api-key rule
        let apiKey = "AIzaIOS-hardcoded-api-key-1234567890"
        let url = URL(string: "https://api.example.com/profile?key=\(apiKey)")!
        URLSession.shared.dataTask(with: url).resume()
    }
}
