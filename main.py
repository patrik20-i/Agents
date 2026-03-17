"""CLI entrypoint wired to utility tools."""

from tool import current_time, search_google, weather_check


def show_menu() -> None:
	print("\n=== Basic Tools Menu ===")
	print("1) Weather check")
	print("2) Search Google")
	print("3) Current time")
	print("4) Exit")


def run() -> None:
	while True:
		show_menu()
		choice = input("Choose an option (1-4): ").strip()

		if choice == "1":
			city = input("Enter city: ")
			print(weather_check(city))

		elif choice == "2":
			query = input("Search query: ")
			open_choice = input("Open in browser? (y/n): ").strip().lower()
			open_in_browser = open_choice in {"y", "yes"}
			print(search_google(query, open_in_browser=open_in_browser))

		elif choice == "3":
			utc_choice = input("Use UTC? (y/n): ").strip().lower()
			use_utc = utc_choice in {"y", "yes"}
			print(current_time(use_utc=use_utc))

		elif choice == "4":
			print("Goodbye!")
			break

		else:
			print("Invalid choice. Please enter 1, 2, 3, or 4.")


if __name__ == "__main__":
	run()