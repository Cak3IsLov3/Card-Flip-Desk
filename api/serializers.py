
from django.urls import reverse
from rest_framework import serializers

from finance.calculator import ZERO
from finance.models import DEFAULT_CATEGORY, FeeProfile
from inventory.models import Card, CardPhoto, PhotoLabel, Purchase
from sales.models import Listing, ListingStatus, ListingTemplate, Sale


class OwnedPrimaryKeyField(serializers.PrimaryKeyRelatedField):
    """Only objects owned by the logged-in user are valid.

    Another user's id gives the same error as an id that does not exist, so
    the API does not reveal which ids exist.
    """

    def __init__(self, *, owner_field, **kwargs):
        self.owner_field = owner_field
        super().__init__(**kwargs)

    def get_queryset(self):
        request = self.context["request"]
        return super().get_queryset().filter(**{self.owner_field: request.user})


def owned_card_field(**kwargs):
    return OwnedPrimaryKeyField(queryset=Card.objects.all(), owner_field="owner", **kwargs)


class PurchaseSerializer(serializers.ModelSerializer):
    card = owned_card_field()

    class Meta:
        model = Purchase
        fields = ["id", "card", "price", "shipping_in", "date", "source"]
        extra_kwargs = {"price": {"min_value": ZERO}, "shipping_in": {"min_value": ZERO}}


class PhotoSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = CardPhoto
        fields = ["id", "card", "label", "position", "is_main", "width", "height",
                  "content_type", "uploaded_at", "file_url", "thumbnail_url"]
        read_only_fields = ["card", "position", "is_main", "width", "height", "content_type", "uploaded_at"]

    def _url(self, photo, name):
        return self.context["request"].build_absolute_uri(reverse(name, args=[photo.pk]))

    def get_file_url(self, photo) -> str:
        return self._url(photo, "api:photo-file")

    def get_thumbnail_url(self, photo) -> str:
        return self._url(photo, "api:photo-thumbnail")


class PhotoUploadSerializer(serializers.Serializer):
    card = owned_card_field()
    file = serializers.FileField(help_text="JPEG, PNG or WebP; the contents are checked.")
    label = serializers.ChoiceField(choices=PhotoLabel.choices, default=PhotoLabel.OTHER)


class CardSerializer(serializers.ModelSerializer):
    total_cost = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    purchases = PurchaseSerializer(many=True, read_only=True)
    main_photo = serializers.SerializerMethodField()

    class Meta:
        model = Card
        fields = [
            "id", "player", "sport", "set_name", "year", "card_number", "variant", "condition",
            "notes", "status", "listed_since", "held_until", "total_cost", "purchases",
            "main_photo", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_main_photo(self, card) -> int | None:
        main = next((p for p in card.photos.all() if p.is_main), None)
        return main.pk if main else None


class ListingSerializer(serializers.ModelSerializer):
    card = owned_card_field()

    class Meta:
        model = Listing
        fields = ["id", "card", "title", "description", "asking_price", "ebay_item_id", "status", "listed_at"]
        read_only_fields = ["listed_at"]
        extra_kwargs = {"asking_price": {"min_value": ZERO}}

    def validate_status(self, value):
        if value == ListingStatus.SOLD:
            raise serializers.ValidationError("Use POST /sales/ to record a sale.")
        return value


class ListingTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingTemplate
        fields = ["id", "name", "title_pattern", "description_pattern"]


class GenerateListingSerializer(serializers.Serializer):
    template = serializers.IntegerField(required=False, help_text="Id of one of your templates; empty = default.")


class GeneratedListingSerializer(serializers.Serializer):
    title = serializers.CharField()
    full_title = serializers.CharField()
    was_truncated = serializers.BooleanField()
    description = serializers.CharField()
    warnings = serializers.ListField(child=serializers.CharField())


class SaleSerializer(serializers.ModelSerializer):
    card = serializers.IntegerField(source="listing.card_id", read_only=True)
    net_proceeds = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    # Annotation from SaleQuerySet.with_profit(); DecimalField rounds to cents.
    profit = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Sale
        fields = ["id", "card", "listing", "sale_price", "shipping_income", "ebay_commission", "payment_fee",
                  "shipping_cost", "packaging_cost", "net_proceeds", "profit", "sold_at", "buyer_country"]
        read_only_fields = fields


class SaleCreateSerializer(serializers.Serializer):
    card = owned_card_field()
    sale_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=ZERO)
    shipping_income = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=ZERO, default=ZERO)
    shipping_cost = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=ZERO, default=ZERO)
    packaging_cost = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=ZERO, default=ZERO)
    sold_at = serializers.DateField()
    buyer_country = serializers.CharField(max_length=2, required=False, default="")
    category = serializers.CharField(max_length=80, default=DEFAULT_CATEGORY)

    def validate_card(self, card):
        if card.status == "sold":
            raise serializers.ValidationError("This card has already been sold.")
        return card


class FeeProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeProfile
        fields = ["id", "category", "commission_percentage", "fixed_fee", "payment_percentage", "valid_from"]


class CalculatorInputSerializer(serializers.Serializer):
    fee_profile = OwnedPrimaryKeyField(queryset=FeeProfile.objects.all(), owner_field="user")
    shipping_income = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=ZERO, default=ZERO)
    shipping_cost = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=ZERO, default=ZERO)
    packaging_cost = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=ZERO, default=ZERO)
    purchase_cost = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=ZERO, default=ZERO)


class ForwardCalculatorSerializer(CalculatorInputSerializer):
    sale_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=ZERO)


class ReverseCalculatorSerializer(CalculatorInputSerializer):
    target_profit = serializers.DecimalField(max_digits=10, decimal_places=2)


class CalculatorResultSerializer(serializers.Serializer):
    required_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    gross = serializers.DecimalField(max_digits=12, decimal_places=2)
    commission = serializers.DecimalField(max_digits=12, decimal_places=2)
    payment_fee = serializers.DecimalField(max_digits=12, decimal_places=2)
    shipping_cost = serializers.DecimalField(max_digits=12, decimal_places=2)
    packaging_cost = serializers.DecimalField(max_digits=12, decimal_places=2)
    net_proceeds = serializers.DecimalField(max_digits=12, decimal_places=2)
    purchase_cost = serializers.DecimalField(max_digits=12, decimal_places=2)
    profit = serializers.DecimalField(max_digits=12, decimal_places=2)
    margin = serializers.DecimalField(max_digits=7, decimal_places=1, allow_null=True)
    is_loss = serializers.BooleanField()
