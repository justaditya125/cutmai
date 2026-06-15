from locust import HttpUser, task, between

class CampusUser(HttpUser):
    wait_time = between(2, 6)

    def on_start(self):
        self.client.get("/", name="Home")

    @task(5)
    def dashboard_flow(self):
        self.client.get("/dashboard", name="Dashboard")

    @task(4)
    def practice_flow(self):
        self.client.get("/practice", name="Practice")

    @task(3)
    def analytics_flow(self):
        self.client.get("/analytics", name="Analytics")

    @task(2)
    def tutor_flow(self):
        self.client.get("/tutor", name="Tutor")

    @task(1)
    def full_journey(self):
        self.client.get("/dashboard", name="Journey-Dashboard")
        self.client.get("/practice", name="Journey-Practice")
        self.client.get("/analytics", name="Journey-Analytics")
        self.client.get("/tutor", name="Journey-Tutor")

#locust -f load_test.py --host https://campusone.cutm.ac.in