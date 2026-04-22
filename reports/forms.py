from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User, Report


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=False, label="Email (optional)")

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = 'user'      # registration always creates regular user
        user.email = self.cleaned_data.get('email', '')
        if commit:
            user.save()
        return user


class ReportForm(forms.ModelForm):
    latitude = forms.DecimalField(
        max_digits=9, decimal_places=6,
        widget=forms.HiddenInput(),
        required=True,
    )
    longitude = forms.DecimalField(
        max_digits=9, decimal_places=6,
        widget=forms.HiddenInput(),
        required=True,
    )

    class Meta:
        model = Report
        fields = ['title', 'description', 'image', 'latitude', 'longitude']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Brief title for the waste issue',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 4,
                'placeholder': 'Describe the waste problem in detail...',
            }),
            'image': forms.ClearableFileInput(attrs={
                'class': 'form-file',
                'accept': 'image/*',
            }),
        }

    def clean(self):
        cleaned = super().clean()
        lat = cleaned.get('latitude')
        lon = cleaned.get('longitude')
        if not lat or not lon:
            raise forms.ValidationError(
                "Please click on the map to select the report location."
            )
        return cleaned