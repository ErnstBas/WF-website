import datetime
import braintree
from django.db.models.query import QuerySet
from django.http import HttpRequest
from django.test import RequestFactory, TestCase, Client
from django.urls import reverse
import json
from unittest.mock import Mock, patch
from wagtail.models import Site

from accounts.factories import UserFactory
from accounts.models import User
from subscription.factories import SubscriptionFactory
from subscription.forms import SubscriptionCreateForm
from subscription.models import (
    SUBSCRIPTION_PRICE_COMPONENTS,
    MagazineFormatChoices,
    MagazinePriceGroupChoices,
    ManageSubscriptionPage,
    Subscription,
    SubscriptionIndexPage,
    process_subscription_form,
)
from home.models import HomePage
from .views import GRACE_PERIOD_DAYS, handle_subscription_webhook


class SubscriptionWebhookTestCase(TestCase):
    def setUp(self) -> None:
        braintree_configuration = braintree.Configuration(
            braintree.Environment.Sandbox,  # type: ignore
            merchant_id="123",
            public_key="123",
            private_key="123",
        )
        # create a mock BraintreeSubscription
        self.braintree_subscription_with_paid_through_date = braintree.Subscription(
            gateway=braintree.BraintreeGateway(braintree_configuration),
            attributes={
                "id": "test_subscription_id",
                "paid_through_date": datetime.date(2022, 7, 1),
            },
        )

        self.braintree_subscription_without_paid_through_date = braintree.Subscription(
            gateway=braintree.BraintreeGateway(braintree_configuration),
            attributes={
                "id": "test_subscription_id",
            },
        )

        # Create a User and Subscription
        self.user = User.objects.create_user(  # type: ignore
            email="test@user.com",
            password="testpassword",
        )

        self.subscription = Subscription.objects.create(
            user=self.user,
            braintree_subscription_id="test_subscription_id",
            end_date=datetime.date(2021, 1, 1),
        )

    def test_handle_subscription_webhook_with_paid_through_date(self) -> None:
        handle_subscription_webhook(
            self.braintree_subscription_with_paid_through_date,
        )

        self.subscription.refresh_from_db()

        self.assertEqual(
            self.subscription.end_date,
            datetime.date(2022, 7, 6),
        )

    def test_handle_subscription_webhook_without_paid_through_date(self) -> None:
        handle_subscription_webhook(
            self.braintree_subscription_without_paid_through_date,
        )

        self.subscription.refresh_from_db()

        self.assertEqual(
            self.subscription.end_date,
            datetime.date(2022, 1, 6),
        )

    def tearDown(self) -> None:
        self.subscription.delete()
        self.user.delete()
        return super().tearDown()


class SubscriptionTestCase(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(  # type: ignore
            email="test@user.com",
            password="testpassword",  # pragma: no cover
        )

    def test_subscription_create_correct_price(self) -> None:
        # create a dictionary of all keys and values for a Subscription
        subscription_data = {
            "recurring": True,
            "start_date": datetime.date.today(),
            "end_date": datetime.date.today(),
            "subscriber_given_name": "John",
            "subscriber_family_name": "Woolman",
            "subscriber_organization": "Western Friend",
            "subscriber_street_address": "123 Main St",
            "subscriber_street_address_line_2": "Suite 100",
            "subscriber_postal_code": "12345",
            "subscriber_address_locality": "Portland",
            "subscriber_address_region": "OR",
            "subscriber_address_country": "United States",
            "user": self.user,
            "paid": True,
            "braintree_subscription_id": "test_subscription_id",
        }
        magazine_formats = MagazineFormatChoices.choices
        price_groups = MagazinePriceGroupChoices.choices

        # Iterate through all possible combinations of
        # magazine_format and price_group
        for magazine_format in magazine_formats:
            for price_group in price_groups:
                magazine_format_choice = magazine_format[0]
                price_group_choice = price_group[0]

                subscription_data["magazine_format"] = magazine_format_choice
                subscription_data["price_group"] = price_group_choice

                expected_price = SUBSCRIPTION_PRICE_COMPONENTS[price_group_choice][
                    magazine_format_choice
                ]

                subscription = Subscription.objects.create(**subscription_data)

                # check that the Subscription was created with the correct price
                # as a sub test for improved error reporting
                subtest_message = f"Subscription price should be {expected_price} for magazine format {magazine_format_choice} and price group {price_group_choice}"  # noqa: E501
                with self.subTest(
                    msg=subtest_message,
                ):
                    self.assertEqual(
                        subscription.price,
                        expected_price,
                    )

                subscription.delete()

    def test_subscription_get_total_cost(self) -> None:
        magazine_formats = MagazineFormatChoices.choices
        price_groups = MagazinePriceGroupChoices.choices

        # Iterate through all possible combinations of
        # magazine_format and price_group
        for magazine_format in magazine_formats:
            for price_group in price_groups:
                magazine_format_choice = magazine_format[0]
                price_group_choice = price_group[0]

                subscription = Subscription.objects.create(
                    magazine_format=magazine_format_choice,
                    price_group=price_group_choice,
                    user=self.user,
                )

                expected_price = SUBSCRIPTION_PRICE_COMPONENTS[price_group_choice][
                    magazine_format_choice
                ]

                # check that the Subscription was created with the correct price
                # as a sub test for improved error reporting
                subtest_message = f"Subscription price should be {expected_price} for magazine format {magazine_format_choice} and price group {price_group_choice}"  # noqa: E501
                with self.subTest(
                    msg=subtest_message,
                ):
                    self.assertEqual(
                        subscription.get_total_cost(),
                        expected_price,
                    )

                subscription.delete()

    def test_subscription_full_name(self) -> None:
        # Test all possible permutations of the subscriber_given_name and
        # subscriber_family_name fields
        given_names = ["", "John"]
        family_names = ["", "Woolman"]

        for name in given_names:
            for lastname in family_names:
                subscription = Subscription.objects.create(
                    subscriber_given_name=name,
                    subscriber_family_name=lastname,
                    user=self.user,
                )

                # If name and lastname are empty, full_name should return a space
                if name == "" and lastname == "":
                    expected_full_name = ""
                    self.assertEqual(
                        subscription.subscriber_full_name,
                        expected_full_name,
                    )

                # If only lastname is empty, full_name should return just the name
                elif lastname == "":
                    self.assertEqual(
                        subscription.subscriber_full_name,
                        name,
                    )

                # If only name is empty, full_name should return just the lastname
                elif name == "":
                    self.assertEqual(
                        subscription.subscriber_full_name,
                        lastname,
                    )

                # If both are not empty, full_name should return name and lastname
                else:
                    self.assertEqual(
                        subscription.subscriber_full_name,
                        f"{name} {lastname}",
                    )

                subscription.delete()

    def test_subscription_str(self) -> None:
        subscription = Subscription.objects.create(
            id=123,
            user=self.user,
            braintree_subscription_id="test_subscription_id",
        )

        expected_subscription_str = "Subscription 123"

        self.assertEqual(
            str(subscription),
            expected_subscription_str,
        )

        subscription.delete()

    def tearDown(self) -> None:
        self.user.delete()
        return super().tearDown()


class SubscriptionWebhookViewTests(TestCase):
    def setUp(self) -> None:
        self.subscription = SubscriptionFactory(
            braintree_subscription_id="test_subscription_id",
        )

        self.client = Client()
        self.url = reverse("braintree-subscription-webhook")

        self.webhook_notification = {
            "bt_signature": "signature",
            "bt_payload": "payload",
        }

    @patch("subscription.views.braintree_gateway.webhook_notification.parse")
    def test_csrf_exempt(
        self,
        mock_parse: Mock,
    ) -> None:
        # Get the current date and time
        now = datetime.datetime.now()
        one_year_later = now + datetime.timedelta(days=365)

        # Set paid_through_date to one year from now
        mock_braintree_subscription = Mock()
        mock_braintree_subscription.id = self.subscription.braintree_subscription_id  # type: ignore  # noqa: E501
        mock_braintree_subscription.paid_through_date = one_year_later

        mock_webhook_notification = Mock()
        mock_webhook_notification.kind = "subscription_charged_successfully"
        mock_webhook_notification.subscription = mock_braintree_subscription

        # mock parse method to return the mock notification
        mock_parse.return_value = mock_webhook_notification

        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(
            self.url,
            data=json.dumps(self.webhook_notification),
            content_type="application/json",
        )

        # assert that parse was called with the correct arguments
        mock_parse.assert_called_once_with(
            self.webhook_notification["bt_signature"],
            self.webhook_notification["bt_payload"],
        )

        # check the response status code
        self.assertEqual(response.status_code, 200)

    @patch("subscription.views.braintree_gateway.webhook_notification.parse")
    def test_subscription_end_date_updated_with_paid_through_date(
        self,
        mock_parse: Mock,
    ) -> None:
        # Get the current date without time
        today = datetime.date.today()
        one_year_later = today + datetime.timedelta(days=365)

        # Set paid_through_date to one year from now
        mock_braintree_subscription = Mock()
        mock_braintree_subscription.id = self.subscription.braintree_subscription_id  # type: ignore  # noqa: E501
        mock_braintree_subscription.paid_through_date = one_year_later

        mock_webhook_notification = Mock()
        mock_webhook_notification.kind = "subscription_charged_successfully"
        mock_webhook_notification.subscription = mock_braintree_subscription

        # mock parse method to return the mock notification
        mock_parse.return_value = mock_webhook_notification

        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(
            self.url,
            data=json.dumps(self.webhook_notification),
            content_type="application/json",
        )

        # assert that parse was called with the correct arguments
        mock_parse.assert_called_once_with(
            self.webhook_notification["bt_signature"],
            self.webhook_notification["bt_payload"],
        )

        # check the response status code
        self.assertEqual(response.status_code, 200)

        # Refresh subscription from db
        self.subscription.refresh_from_db()  # type: ignore

        # check that the end_date is updated
        expected_end_date = one_year_later + GRACE_PERIOD_DAYS
        self.assertEqual(self.subscription.end_date, expected_end_date)  # type: ignore

    @patch("subscription.views.braintree_gateway.webhook_notification.parse")
    def test_subscription_end_date_updated_without_paid_through_date(
        self,
        mock_parse: Mock,
    ) -> None:
        # Calculate the expected end_date
        one_year_with_grace_period = datetime.timedelta(days=365) + GRACE_PERIOD_DAYS
        expected_end_date = self.subscription.end_date + one_year_with_grace_period  # type: ignore  # noqa: E501

        # Set up the Braintree subscription mock without paid_through_date
        mock_braintree_subscription = Mock()
        mock_braintree_subscription.id = self.subscription.braintree_subscription_id  # type: ignore  # noqa: E501
        mock_braintree_subscription.paid_through_date = None

        mock_webhook_notification = Mock()
        mock_webhook_notification.kind = "subscription_charged_successfully"
        mock_webhook_notification.subscription = mock_braintree_subscription

        # mock parse method to return the mock notification
        mock_parse.return_value = mock_webhook_notification

        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(
            self.url,
            data=json.dumps(self.webhook_notification),
            content_type="application/json",
        )

        # assert that parse was called with the correct arguments
        mock_parse.assert_called_once_with(
            self.webhook_notification["bt_signature"],
            self.webhook_notification["bt_payload"],
        )

        # check the response status code
        self.assertEqual(response.status_code, 200)

        # Refresh subscription from db
        self.subscription.refresh_from_db()  # type: ignore

        # check that the end_date is updated
        self.assertEqual(self.subscription.end_date, expected_end_date)  # type: ignore


class SubscriptionCreateFormTestCase(TestCase):
    def setUp(self) -> None:
        self.user = UserFactory()
        self.subscription = SubscriptionFactory(user=self.user)

        # Initialize form with data from factory
        self.form_data = {
            "magazine_format": self.subscription.magazine_format,  # type: ignore
            "price_group": self.subscription.price_group,  # type: ignore
            "recurring": self.subscription.recurring,  # type: ignore
            "subscriber_given_name": self.subscription.subscriber_given_name,  # type: ignore # noqa: E501
            "subscriber_family_name": self.subscription.subscriber_family_name,  # type: ignore # noqa: E501
            "subscriber_street_address": self.subscription.subscriber_street_address,  # type: ignore  # noqa: E501
            "subscriber_street_address_line_2": self.subscription.subscriber_street_address_line_2,  # type: ignore  # noqa: E501
            "subscriber_postal_code": self.subscription.subscriber_postal_code,  # type: ignore  # noqa: E501
            "subscriber_address_locality": self.subscription.subscriber_address_locality,  # type: ignore  # noqa: E501
            "subscriber_address_region": self.subscription.subscriber_address_region,  # type: ignore  # noqa: E501
            "subscriber_address_country": self.subscription.subscriber_address_country,  # type: ignore  # noqa: E501
        }
        self.form = SubscriptionCreateForm(data=self.form_data)

    def test_process_subscription_form(self) -> None:
        # Ensure the form is valid
        self.assertTrue(self.form.is_valid())

        # Process the form
        processed_subscription = process_subscription_form(self.form, self.user)  # type: ignore # noqa: E501

        # Ensure the subscription is saved
        self.assertIsInstance(processed_subscription, Subscription)

        # Check the subscription's user is set correctly
        self.assertEqual(processed_subscription.user, self.user)

        # Check the subscription's start date and end date are set correctly
        today = datetime.date.today()
        self.assertEqual(processed_subscription.start_date, today)
        self.assertEqual(processed_subscription.end_date, today)

        # Check the form data is saved correctly in the processed subscription
        for field, value in self.form_data.items():
            self.assertEqual(getattr(processed_subscription, field), value)


class SubscriptionIndexPageTestCase(TestCase):
    def setUp(self) -> None:
        self.user = UserFactory()

        # Create a SubscriptionIndexPage instance and add it to the site tree
        self.site = Site.objects.get(is_default_site=True)

        self.home_page = HomePage(
            title="Home",
        )

        self.site.root_page.add_child(instance=self.home_page)
        self.subscription_index_page = SubscriptionIndexPage(
            title="Subscription",
        )
        self.home_page.add_child(instance=self.subscription_index_page)

        self.factory = RequestFactory()

    def test_subscription_index_page_str(self) -> None:
        subscription_index_page = SubscriptionIndexPage(title="Test Title")
        self.assertEqual(str(subscription_index_page), "Test Title")

    def test_form_in_context_when_not_previously_present(self) -> None:
        request = self.factory.get("/")
        context = self.subscription_index_page.get_context(request)
        self.assertIsInstance(context["form"], SubscriptionCreateForm)

    def test_get_request_serve_index_template(self) -> None:
        mock_request = self.factory.get("/")
        response = self.subscription_index_page.serve(mock_request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.template_name,  # type: ignore
            "subscription/index.html",
        )

    def test_form_in_context_when_previously_submitted(self) -> None:
        request = self.factory.get("/")

        # Create an invalid form
        invalid_form_data = {
            "subscriber_given_name": "",  # This is invalid as it's required
        }
        invalid_form = SubscriptionCreateForm(invalid_form_data)

        request.context = {"form": invalid_form}  # type: ignore

        context = self.subscription_index_page.get_context(request)

        self.assertIsInstance(context["form"], SubscriptionCreateForm)
        self.assertFalse(context["form"].is_valid())

    def test_subscription_price_components_in_page_context(
        self,
    ) -> None:
        subscription_index_page = SubscriptionIndexPage(title="Test Title")
        # create mock HttpRequest
        mock_http_request = Mock(
            spec=HttpRequest,
        )

        context = subscription_index_page.get_context(
            request=mock_http_request,
        )

        self.assertEqual(
            context["subscription_price_components"],
            SUBSCRIPTION_PRICE_COMPONENTS,
        )

    def test_post_request_authenticated_valid_form(self) -> None:
        mock_request = self.factory.post(
            # get URL for the SubscriptionIndexPage
            self.subscription_index_page.url,
            data={
                "magazine_format": "print",
                "price_group": "basic",
                "recurring": True,
                "subscriber_given_name": "John",
                "subscriber_family_name": "Woolman",
                "subscriber_street_address": "123 Main St",
                "subscriber_street_address_line_2": "Suite 100",
                "subscriber_postal_code": "12345",
                "subscriber_address_locality": "Portland",
                "subscriber_address_region": "OR",
                "subscriber_address_country": "United States",
            },
        )
        mock_request.user = self.user  # type: ignore
        mock_request.site = self.site

        response = self.subscription_index_page.serve(mock_request)

        self.assertEqual(response.status_code, 302)

    def test_redirect_unauthenticated_user(self) -> None:
        # make anonymous post request
        mock_request = self.factory.post(
            # get URL for the SubscriptionIndexPage
            self.subscription_index_page.url,  # type: ignore
        )

        response = self.subscription_index_page.serve(mock_request)

        self.assertEqual(response.status_code, 302)
        # redirects us to the login page
        # by getting reverse path to the login page
        login_base_url = reverse("login")[:-1]
        expected_url = f"{login_base_url}?next={self.subscription_index_page.url}"  # type: ignore # noqa: E501
        self.assertEqual(
            response.url,
            expected_url,
        )

    def test_post_request_authenticated_invalid_form(self) -> None:
        # partial form submission is invalid
        invalid_form_data = {
            "magazine_format": "print",
            "price_group": "normal",
        }
        mock_request = self.factory.post(
            # get URL for the SubscriptionIndexPage
            self.subscription_index_page.url,  # type: ignore
            data=invalid_form_data,
        )
        mock_request.user = self.user  # type: ignore
        mock_request.site = self.site

        response = self.subscription_index_page.serve(mock_request)

        # check that an invalid form is returned in the context
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context_data["form"], SubscriptionCreateForm)  # type: ignore # noqa: E501
        self.assertFalse(response.context_data["form"].is_valid())  # type: ignore

    def tearDown(self) -> None:
        Subscription.objects.all().delete()
        self.subscription_index_page.delete()
        self.home_page.delete()
        self.site.delete()
        self.user.delete()  # type: ignore
        return super().tearDown()


class ManageSubscriptionPageTestCase(TestCase):
    def setUp(self) -> None:
        self.user = UserFactory()

        self.subscription = SubscriptionFactory(
            user=self.user,
            braintree_subscription_id="test_subscription_id",
        )

        # Create a SubscriptionIndexPage instance and add it to the site tree
        self.site = Site.objects.get(is_default_site=True)

        self.home_page = HomePage(
            title="Home",
        )

        self.site.root_page.add_child(instance=self.home_page)
        self.manage_subscription_page = ManageSubscriptionPage(
            title="Manage Subscription",
        )
        self.home_page.add_child(instance=self.manage_subscription_page)

        self.factory = RequestFactory()

    def tearDown(self) -> None:
        Subscription.objects.all().delete()
        self.manage_subscription_page.delete()
        self.home_page.delete()
        self.site.delete()
        self.user.delete()  # type: ignore
        return super().tearDown()

    def test_manage_subscription_with_user_subscriptions(self) -> None:
        # create mock HttpRequest
        mock_http_request = Mock(
            spec=HttpRequest,
            user=self.user,
        )

        context = self.manage_subscription_page.get_context(
            request=mock_http_request,
        )

        # assert that context subscriptions
        # is a QuerySet of Subscriptions
        self.assertIsInstance(context["subscriptions"], QuerySet)
        for subscription in context["subscriptions"]:
            self.assertIsInstance(subscription, Subscription)

        # assert that self.subscription is in the subscriptions queryset
        self.assertIn(self.subscription, context["subscriptions"])

    def test_manage_subscription_without_user_subscriptions(self) -> None:
        # create mock HttpRequest
        mock_http_request = Mock(
            spec=HttpRequest,
            user=UserFactory(),
        )

        context = self.manage_subscription_page.get_context(
            request=mock_http_request,
        )

        # assert that context subscriptions
        # is an empty QuerySet
        self.assertIsInstance(context["subscriptions"], QuerySet)
        self.assertEqual(len(context["subscriptions"]), 0)
