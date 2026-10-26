from django import forms

from .models import Voter
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
    file = forms.FileField(label="Voter roll (.csv)")

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith(".csv"):
            raise forms.ValidationError("Upload a .csv file.")
        if f.size > 10 * 1024 * 1024:
            raise forms.ValidationError("The file is larger than 10 MB.")
        return f
