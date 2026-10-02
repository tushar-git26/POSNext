<!--
  RfidTray.vue - RFID counter panel (optional module)

  Shown above the cart only when the counter runs in RFID mode (see stores/posRfid.js).
  The tray reader (or a keyboard-wedge bridge) types EPCs into the input; Enter reads them.
  Complete units go straight into the cart with their serial number. Incomplete sets stay
  here with their missing pieces and block payment until fixed or removed.
-->
<template>
	<div class="border-b border-gray-200 bg-white px-3 py-2">
		<div class="flex items-center gap-2">
			<div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-50 text-indigo-600">
				<FeatherIcon name="radio" class="h-4 w-4" />
			</div>
			<input
				ref="inputRef"
				v-model="reads"
				type="text"
				class="h-9 min-w-0 flex-1 rounded-lg border border-gray-300 px-3 text-sm focus:border-indigo-500 focus:outline-none"
				:placeholder="offline ? __('RFID needs a connection') : __('Place garments on the tray or scan a tag')"
				:disabled="offline || rfid.busy"
				@keydown.enter.prevent="readTray"
				@paste="onPaste"
			/>
			<button
				class="h-9 rounded-lg bg-indigo-600 px-3 text-sm font-medium text-white disabled:opacity-50"
				:disabled="offline || rfid.busy || !reads.trim()"
				@click="readTray"
			>
				{{ rfid.busy ? __("Reading…") : __("Read") }}
			</button>
		</div>

		<label v-if="rfid.config.allow_label_fallback" class="mt-1 flex items-center gap-1.5 text-xs text-gray-500">
			<input v-model="labelMode" type="checkbox" class="h-3.5 w-3.5" />
			{{ __("Tag unreadable - scanning printed labels") }}
		</label>

		<div v-for="line in rfid.incomplete" :key="line.serial_no" class="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2">
			<div class="flex items-center justify-between gap-2">
				<div class="min-w-0">
					<div class="truncate text-sm font-medium text-gray-900">{{ line.item_name }}</div>
					<div class="text-xs text-amber-700">{{ __("Set incomplete - read the missing pieces") }}</div>
				</div>
				<button class="shrink-0 text-xs font-medium text-gray-500 hover:text-red-600" @click="rfid.removeUnit(line.serial_no)">
					{{ __("Remove") }}
				</button>
			</div>
			<div class="mt-1.5 flex flex-wrap gap-1">
				<span
					v-for="p in line.pieces"
					:key="p.component"
					:class="[
						'rounded-full px-2 py-0.5 text-xs font-medium',
						p.verified ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700',
					]"
				>
					{{ p.verified ? "✓" : "✕" }} {{ p.role }}
				</span>
			</div>
		</div>

		<div v-for="(e, i) in rfid.events" :key="i" class="mt-1.5 rounded-md bg-red-50 px-2 py-1 text-xs text-red-700">
			{{ e.message }}
		</div>
	</div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { FeatherIcon } from "frappe-ui";
import { useToast } from "@/composables/useToast";
import { useItemSearchStore } from "@/stores/itemSearch";
import { usePOSCartStore } from "@/stores/posCart";
import { usePosRfidStore } from "@/stores/posRfid";
import { usePOSShiftStore } from "@/stores/posShift";
import { usePOSSyncStore } from "@/stores/posSync";

const rfid = usePosRfidStore();
const cartStore = usePOSCartStore();
const shiftStore = usePOSShiftStore();
const itemStore = useItemSearchStore();
const syncStore = usePOSSyncStore();
const { showError } = useToast();

const reads = ref("");
const labelMode = ref(false);
const inputRef = ref(null);
const itemCache = new Map();
const offline = computed(() => syncStore.isOffline);

function splitCodes(text) {
	return text
		.split(/[\s,]+/)
		.map((s) => s.trim())
		.filter(Boolean);
}

function onPaste(event) {
	// A pasted batch (one EPC per line) is read immediately.
	const text = event.clipboardData?.getData("text") || "";
	if (splitCodes(text).length > 1) {
		event.preventDefault();
		reads.value = text;
		readTray();
	}
}

async function readTray() {
	const codes = splitCodes(reads.value);
	if (!codes.length) return;
	reads.value = "";
	try {
		await rfid.scan(codes, labelMode.value ? "Barcode" : "RFID");
		await schedulePush();
	} catch (error) {
		showError(error?.messages?.[0] || error?.message || __("RFID read failed"));
	}
	await nextTick();
	inputRef.value?.focus();
}

async function itemDetails(itemCode) {
	if (!itemCache.has(itemCode)) {
		itemCache.set(itemCode, await itemStore.searchByBarcode(itemCode));
	}
	return itemCache.get(itemCode);
}

// Pushes run one after another so a unit is never added twice while item details load.
let pushChain = Promise.resolve();
function schedulePush() {
	pushChain = pushChain.then(pushCompleteUnits).catch(() => {});
	return pushChain;
}

/** Complete units on the tray -> cart lines with their serial numbers. */
async function pushCompleteUnits() {
	for (const line of rfid.pendingForCart()) {
		const details = await itemDetails(line.item_code);
		try {
			cartStore.addItem(
				{
					...details,
					serial_no: line.serial_no,
					has_serial_no: 1,
					quantity: 1,
				},
				1,
				false,
				shiftStore.currentProfile,
			);
			rfid.markInCart(line.serial_no);
		} catch (error) {
			showError(error.message);
		}
	}
}

// Keep the basket in step with the cart: a unit removed from the cart leaves the tray too.
const cartSerials = computed(() => {
	const all = new Set();
	for (const item of cartStore.invoiceItems) {
		for (const s of (item.serial_no || "").split("\n"))
			if (s.trim()) all.add(s.trim());
	}
	return all;
});
watch(cartSerials, (now) => {
	// Only units this tray put into the cart; incomplete sets live in the panel, not the cart.
	for (const serial of [...rfid.inCart]) {
		if (!now.has(serial)) rfid.removeUnit(serial).catch(() => {});
	}
});

// The invoice carries the basket so the server can verify every unit was read.
watch(
	() => rfid.basket,
	() => {
		cartStore.invoiceExtras = rfid.invoiceExtras();
	},
	{ immediate: true },
);

// Covers a basket resumed after a reload: its complete units appear once it loads.
watch(() => rfid.lines, schedulePush, { immediate: true });

onMounted(() => inputRef.value?.focus());
</script>
