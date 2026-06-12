from locust import HttpUser, task, between

class CampusUser(HttpUser):
    wait_time = between(1, 3)

    @task(4)
    def dashboard(self):
        self.client.get("/dashboard")

    @task(3)
    def practice(self):
        self.client.get("/practice")

    @task(2)
    def analytics(self):
        self.client.get("/analytics")

    @task(1)
    def tutor(self):
        self.client.get("/tutor")

#locust -f load_test.py --host https://campusone.cutm.ac.in -u 10 -r 2