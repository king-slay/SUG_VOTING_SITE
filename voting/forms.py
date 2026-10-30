from django import forms
from django.core.files.uploadedfile import UploadedFile

from .models import Candidate, Election, Position, Voter
from .roll import clean_reg_number, normalize


class FaceImageField(forms.CharField):
    """Hidden field holding the webcam snapshot as a base64 data URL."""

    widget = forms.HiddenInput

    def __init__(self, **kwargs):
        kwargs.setdefault("error_messages", {"required": "Please capture your face before continuing."})
        super().__init__(**kwargs)


class RegistrationForm(forms.Form):
    reg_number = forms.CharField(label="Registration number", max_length=30)
    full_name = forms.CharField(label="Full name (as on the voter roll)", max_length=150)
    faculty = forms.CharField(max_length=100)
    department = forms.CharField(max_length=100)
    level = forms.CharField(max_length=10)
    email = forms.EmailField(label="Email address")
    phone = forms.CharField(label="Phone number", max_length=20)
    face_image = FaceImageField()

    def clean_reg_number(self):
        return clean_reg_number(self.cleaned_data["reg_number"])

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        voter = Voter.objects.filter(reg_number=data["reg_number"]).first()
        mismatch = voter is None or any(
            normalize(getattr(voter, key)) != normalize(data[key])
            for key in ("full_name", "faculty", "department", "level")
        )
        if mismatch:
            raise forms.ValidationError(
                "These details do not match the voter roll. Check your registration number, "
                "name, faculty, department and level, or contact the electoral committee."
            )
        if voter.is_registered:
            raise forms.ValidationError(
                "This registration number has already been registered. If this was not you, "
                "contact the electoral committee."
            )
        data["voter"] = voter
        return data


class VoteStartForm(forms.Form):
    reg_number = forms.CharField(label="Registration number", max_length=30)
    face_image = FaceImageField()

    def clean_reg_number(self):
        return clean_reg_number(self.cleaned_data["reg_number"])


class RollUploadForm(forms.Form):
    file = forms.FileField(label="Voter roll (.csv or .xlsx)")

    def clean_file(self):
        f = self.cleaned_data["file"]
        name = f.name.lower()
        if name.endswith(".xls"):
            raise forms.ValidationError(
                "Old Excel .xls files are not supported. In Excel choose Save As, then .xlsx or CSV UTF-8."
            )
        if not name.endswith((".csv", ".xlsx")):
            raise forms.ValidationError("Upload a .csv or .xlsx file.")
        if f.size > 10 * 1024 * 1024:
            raise forms.ValidationError("The file is larger than 10 MB.")
        return f


class ElectionForm(forms.ModelForm):
    class Meta:
        model = Election
        fields = ["title"]
        labels = {"title": "Election title"}


class PositionForm(forms.ModelForm):
    class Meta:
        model = Position
        fields = ["title", "order"]
        labels = {"title": "Position", "order": "Order on the ballot"}
        help_texts = {"order": "Lower numbers appear first."}

    def __init__(self, *args, election, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.election = election

    def clean_title(self):
        title = " ".join(self.cleaned_data["title"].split())
        clash = Position.objects.filter(election=self.instance.election, title__iexact=title)
        if clash.exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This election already has that position.")
        return title


PHOTO_TYPES = (".jpg", ".jpeg", ".png", ".webp")


class CandidateForm(forms.ModelForm):
    class Meta:
        model = Candidate
        fields = ["name", "department", "manifesto", "photo"]
        labels = {"name": "Full name", "photo": "Photo (optional)"}
        widgets = {
            "manifesto": forms.Textarea(attrs={"rows": 6}),
            "photo": forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
        }

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if isinstance(photo, UploadedFile):
            if not photo.name.lower().endswith(PHOTO_TYPES):
                raise forms.ValidationError("Use a JPG, PNG or WebP photo.")
            if photo.size > 3 * 1024 * 1024:
                raise forms.ValidationError("The photo is larger than 3 MB.")
        return photo
