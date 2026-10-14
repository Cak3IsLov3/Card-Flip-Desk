"""REST API (DRF).

Two layers of access control:
1. Every queryset is filtered on the logged-in user, so other users' objects
   do not exist as far as the API is concerned (404, not 403).
2. `IsOwner` checks the object again, in case a new view forgets the filter.
References to cards or profiles in the input only accept your own objects
(see `OwnedPrimaryKeyField`).

Business rules live in the existing services; the API calls them.
"""

from django.db.models import Prefetch
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from finance.calculator import CostInput, calculate, required_price
from finance.models import FeeProfile
from inventory import photos as photo_service
from inventory.models import Card, CardPhoto, CardStatus, Purchase
from sales import listing_generator as gen
from sales.models import Listing, ListingStatus, ListingTemplate, Sale
from sales.services import NoFeeProfile, register_sale

from . import serializers as s


class IsOwner(permissions.BasePermission):
    """Safety net next to the filtered querysets."""

    def has_object_permission(self, request, view, obj):
        return view.owner_of(obj) == request.user


class OwnedViewSetMixin:
    permission_classes = [permissions.IsAuthenticated, IsOwner]
    owner_path: str  # e.g. "owner" or "card__owner"

    def owner_of(self, obj):
        for part in self.owner_path.split("__"):
            obj = getattr(obj, part)
        return obj

    def owned(self, qs):
        if getattr(self, "swagger_fake_view", False):  # schema generation, no real user
            return qs.none()
        return qs.filter(**{self.owner_path: self.request.user})


# --- cards -------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Search player, set, number and notes"),
            OpenApiParameter("status", str, enum=[c.value for c in CardStatus]),
            OpenApiParameter("set_name", str, description="Part of the set name"),
            OpenApiParameter("year", int),
        ]
    )
)
class CardViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    serializer_class = s.CardSerializer
    owner_path = "owner"

    def get_queryset(self):
        qs = self.owned(Card.objects.all()).with_cost().prefetch_related(
            "purchases", Prefetch("photos", CardPhoto.objects.order_by("position", "id"))
        )
        params = self.request.query_params
        qs = qs.search(params.get("q", "").strip())
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("set_name"):
            qs = qs.filter(set_name__icontains=params["set_name"])
        if params.get("year", "").isdigit():
            qs = qs.filter(year=int(params["year"]))
        return qs.order_by("-created_at", "-id")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @extend_schema(request=s.GenerateListingSerializer, responses=s.GeneratedListingSerializer)
    @action(detail=True, methods=["post"], url_path="generate-listing")
    def generate_listing(self, request, pk=None):
        """Title and description from a template, with checks (length, fields, photos)."""
        card = self.get_object()
        params = s.GenerateListingSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        template_id = params.validated_data.get("template")
        if template_id:
            tpl = get_object_or_404(ListingTemplate, pk=template_id, user=request.user)
            patterns = (tpl.title_pattern, tpl.description_pattern)
        else:
            patterns = (gen.DEFAULT_TITLE_PATTERN, gen.DEFAULT_DESCRIPTION_PATTERN)
        result = gen.generate(card, *patterns)
        data = {**result.__dict__, "was_truncated": result.was_truncated}
        return Response(s.GeneratedListingSerializer(data).data)


class PurchaseViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    serializer_class = s.PurchaseSerializer
    owner_path = "card__owner"

    def get_queryset(self):
        qs = self.owned(Purchase.objects.select_related("card"))
        if card := self.request.query_params.get("card"):
            qs = qs.filter(card_id=card) if card.isdigit() else qs.none()
        return qs.order_by("-date", "-id")


# --- photos ------------------------------------------------------------------

@extend_schema_view(
    create=extend_schema(request={"multipart/form-data": s.PhotoUploadSerializer}, responses={201: s.PhotoSerializer}),
    partial_update=extend_schema(description="Only `label` can be changed."),
)
class PhotoViewSet(
    OwnedViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = s.PhotoSerializer
    owner_path = "card__owner"
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = self.owned(CardPhoto.objects.select_related("card"))
        if card := self.request.query_params.get("card"):
            qs = qs.filter(card_id=card) if card.isdigit() else qs.none()
        return qs.order_by("card_id", "position", "id")

    def create(self, request):
        upload = s.PhotoUploadSerializer(data=request.data, context={"request": request})
        upload.is_valid(raise_exception=True)
        data = upload.validated_data
        try:
            (photo,) = photo_service.add_photos(data["card"], [data["file"]], data["label"])
        except photo_service.PhotoError as exc:
            raise ValidationError({"file": exc.messages}) from None
        return Response(self.get_serializer(photo).data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, photo):
        photo_service.delete_photo(photo)

    @extend_schema(request=None, responses=s.PhotoSerializer)
    @action(detail=True, methods=["post"], url_path="set-main")
    def set_main(self, request, pk=None):
        photo = self.get_object()
        photo_service.set_main(photo)
        photo.refresh_from_db()
        return Response(self.get_serializer(photo).data)

    @extend_schema(responses={(200, "image/*"): OpenApiResponse(description="The image file")})
    @action(detail=True, methods=["get"])
    def file(self, request, pk=None):
        photo = self.get_object()
        return self._serve(photo.image, photo.content_type)

    @extend_schema(responses={(200, "image/*"): OpenApiResponse(description="The thumbnail")})
    @action(detail=True, methods=["get"])
    def thumbnail(self, request, pk=None):
        photo = self.get_object()
        return self._serve(photo.thumbnail, photo.content_type)

    def _serve(self, field, content_type):
        try:
            response = FileResponse(field.open("rb"), content_type=content_type)
        except FileNotFoundError:
            raise Http404 from None
        response["Cache-Control"] = "private, max-age=3600"
        return response


# --- listings, templates, sales ---------------------------------------------

class ListingViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    serializer_class = s.ListingSerializer
    owner_path = "card__owner"

    def get_queryset(self):
        qs = self.owned(Listing.objects.select_related("card"))
        if st := self.request.query_params.get("status"):
            qs = qs.filter(status=st)
        return qs.order_by("-id")

    def perform_update(self, serializer):
        if serializer.instance.status == ListingStatus.SOLD:
            raise ValidationError("A sold listing can no longer be changed.")
        serializer.save()

    def perform_destroy(self, listing):
        if listing.status == ListingStatus.SOLD:
            raise ValidationError("A sold listing belongs to a sale and cannot be deleted.")
        listing.delete()


class ListingTemplateViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    serializer_class = s.ListingTemplateSerializer
    owner_path = "user"

    def get_queryset(self):
        return self.owned(ListingTemplate.objects.all())

    def _validate(self, serializer):
        for field in ("title_pattern", "description_pattern"):
            unknown = gen.unknown_placeholders(serializer.validated_data.get(field, ""))
            if unknown:
                raise ValidationError({field: ["Unknown placeholder(s): " + ", ".join(unknown)]})
        name = serializer.validated_data.get("name")
        clash = ListingTemplate.objects.filter(user=self.request.user, name__iexact=name)
        if serializer.instance:
            clash = clash.exclude(pk=serializer.instance.pk)
        if name and clash.exists():
            raise ValidationError({"name": ["You already have a template with this name."]})

    def perform_create(self, serializer):
        self._validate(serializer)
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        self._validate(serializer)
        serializer.save()


@extend_schema_view(create=extend_schema(request=s.SaleCreateSerializer, responses={201: s.SaleSerializer}))
class SaleViewSet(OwnedViewSetMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                  mixins.CreateModelMixin, viewsets.GenericViewSet):
    """Sales. Creating one calculates the fees with the fee profile in force."""

    serializer_class = s.SaleSerializer
    owner_path = "listing__card__owner"

    def get_queryset(self):
        return self.owned(Sale.objects.with_profit().select_related("listing__card")).order_by("-sold_at", "-id")

    def create(self, request):
        data = s.SaleCreateSerializer(data=request.data, context={"request": request})
        data.is_valid(raise_exception=True)
        fields = dict(data.validated_data)
        card = fields.pop("card")
        try:
            sale = register_sale(card, **fields)
        except NoFeeProfile as exc:
            raise ValidationError({"category": [str(exc)]}) from None
        sale = self.get_queryset().get(pk=sale.pk)
        return Response(self.get_serializer(sale).data, status=status.HTTP_201_CREATED)


class FeeProfileViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    serializer_class = s.FeeProfileSerializer
    owner_path = "user"

    def get_queryset(self):
        return self.owned(FeeProfile.objects.all())

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


# --- calculator --------------------------------------------------------------

def _result(result, price=None):
    data = {**result.__dict__, "is_loss": result.is_loss}
    if price is not None:
        data["required_price"] = price
    return s.CalculatorResultSerializer(data).data


class CalculatorView(APIView):
    @extend_schema(request=s.ForwardCalculatorSerializer, responses=s.CalculatorResultSerializer,
                   summary="Profit at a sale price")
    def post(self, request):
        inp = s.ForwardCalculatorSerializer(data=request.data, context={"request": request})
        inp.is_valid(raise_exception=True)
        d = dict(inp.validated_data)
        fees = d.pop("fee_profile").to_fees()
        return Response(_result(calculate(CostInput(**d), fees)))


class ReverseCalculatorView(APIView):
    @extend_schema(request=s.ReverseCalculatorSerializer, responses=s.CalculatorResultSerializer,
                   summary="Lowest asking price for a target profit")
    def post(self, request):
        inp = s.ReverseCalculatorSerializer(data=request.data, context={"request": request})
        inp.is_valid(raise_exception=True)
        d = dict(inp.validated_data)
        fees = d.pop("fee_profile").to_fees()
        target = d.pop("target_profit")
        try:
            price = required_price(target, fees, **d)
        except ValueError as exc:
            raise ValidationError({"fee_profile": [str(exc)]}) from None
        return Response(_result(calculate(CostInput(sale_price=price, **d), fees), price))


class TokenView(ObtainAuthToken):
    """Exchange username and password for an API token (max. 10 per minute)."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "token"
