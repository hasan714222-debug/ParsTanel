package manage

import (
	"reflect"
	"testing"
)

func TestReorderPrimary(t *testing.T) {
	oldPrimary := "1.1.1.1:443"
	fallbacks := []string{"2.2.2.2:443", "3.3.3.3:443"}
	newPrimary := "2.2.2.2:443"

	gotPrimary, gotFallbacks := reorderPrimary(oldPrimary, fallbacks, newPrimary)
	if gotPrimary != newPrimary {
		t.Fatalf("primary = %q, want %q", gotPrimary, newPrimary)
	}
	wantFallbacks := []string{"1.1.1.1:443", "3.3.3.3:443"}
	if !reflect.DeepEqual(gotFallbacks, wantFallbacks) {
		t.Fatalf("fallbacks = %v, want %v", gotFallbacks, wantFallbacks)
	}
}
