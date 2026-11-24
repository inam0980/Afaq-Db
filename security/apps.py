from django.apps import AppConfig


class SecurityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "security"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in, user_login_failed

        from security import services

        def on_failed(sender, credentials, request=None, **kwargs):
            services.record(credentials.get("username", ""), request, successful=False)

        def on_success(sender, request, user, **kwargs):
            services.record(user.get_username(), request, successful=True, user=user)

        user_login_failed.connect(on_failed, dispatch_uid="security_login_failed")
        user_logged_in.connect(on_success, dispatch_uid="security_logged_in")
