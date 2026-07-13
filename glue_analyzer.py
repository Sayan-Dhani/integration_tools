import cv2
import numpy as np
import argparse
import sys

# --- Configuration ---
# You can adjust these values if needed
RESIZE_WIDTH = 1200  # Resize images wider than this for better display
MANUAL_BRUSH_SIZE = 10  # Brush size for manual correction
INSTRUCTION_FONT_SCALE = 0.6
INSTRUCTION_FONT_THICKNESS = 1


class GlueContactAnalyzer:
    """
    An interactive tool to analyze glue contact area in images.
    Allows for:
    1. Polygonal ROI selection.
    2. Interactive thresholding for automatic segmentation.
    3. Manual correction of the segmentation.
    4. Calculation of contact area percentages.
    """

    def __init__(self, image_path):
        self.image_path = image_path
        self.original_image = cv2.imread(image_path)

        if self.original_image is None:
            print(f"Error: Could not load image from {image_path}")
            sys.exit(1)

        # Resize image if it's too large for the screen
        h, w = self.original_image.shape[:2]
        if w > RESIZE_WIDTH:
            self.scale_factor = RESIZE_WIDTH / w
            new_h = int(h * self.scale_factor)
            self.image = cv2.resize(self.original_image, (RESIZE_WIDTH, new_h))
        else:
            self.scale_factor = 1.0
            self.image = self.original_image.copy()

        # Initialize state variables
        self.roi_points = []
        self.roi_mask = None
        self.manual_good_mask = np.zeros(self.image.shape[:2], dtype=np.uint8)
        self.manual_bad_mask = np.zeros(self.image.shape[:2], dtype=np.uint8)

        # For perimeter drawing mode
        self.perimeter_points = []
        self.drawing_perimeter = False

        # We will work on the blue channel, as the glue is blueish/gray
        # and has good contrast with the black carbon fiber.
        self.gray_image = self.image[:, :, 0]  # Using Blue channel

        self.threshold_value = 120  # Initial threshold value
        self.use_advanced_segmentation = (
            False  # Toggle between simple threshold and gradient-corrected threshold
        )
        self.invert_logic = False  # Whether to invert the segmentation logic

        # Gradient correction parameters
        self.gradient_kernel_size = 50  # Size of kernel for estimating local background
        self.gradient_correction_strength = (
            1.0  # How much to apply the correction (0.0 to 1.0)
        )

        # Display options
        self.show_overlay = True  # Whether to show green/red overlay
        self.show_corrected_image = False  # Whether to show gradient-corrected image
        self.show_help_text = True  # Whether to show instruction text overlay

        self.mode = "ROI_SELECT"  # Modes: 'ROI_SELECT', 'THRESHOLD', 'MANUAL_GOOD', 'MANUAL_BAD', 'PERIMETER_GOOD', 'PERIMETER_BAD'

        self.window_name = "Glue Contact Analyzer"
        cv2.namedWindow(self.window_name)
        cv2.setMouseCallback(self.window_name, self.mouse_callback)

    def mouse_callback(self, event, x, y, flags, param):
        """Handles all mouse interactions."""
        if self.mode == "ROI_SELECT":
            if event == cv2.EVENT_LBUTTONDOWN:
                self.roi_points.append((x, y))
                print(f"Added ROI point: ({x}, {y})")
            elif event == cv2.EVENT_RBUTTONDOWN:
                if self.roi_points:
                    self.roi_points.pop()
                    print("Removed last ROI point.")

        elif self.mode in ["PERIMETER_GOOD", "PERIMETER_BAD"]:
            if event == cv2.EVENT_LBUTTONDOWN:
                if not self.drawing_perimeter:
                    # Start new perimeter
                    self.perimeter_points = [(x, y)]
                    self.drawing_perimeter = True
                    print(f"Started drawing perimeter at ({x}, {y})")
                else:
                    # Add point to current perimeter
                    self.perimeter_points.append((x, y))
                    print(f"Added perimeter point: ({x}, {y})")
            elif event == cv2.EVENT_MBUTTONDOWN:  # Middle click to complete
                if self.drawing_perimeter and len(self.perimeter_points) > 2:
                    # Complete the perimeter and fill it
                    target_mask = (
                        self.manual_good_mask
                        if self.mode == "PERIMETER_GOOD"
                        else self.manual_bad_mask
                    )
                    cv2.fillPoly(target_mask, [np.array(self.perimeter_points)], 255)
                    print(
                        f"Completed perimeter with {len(self.perimeter_points)} points"
                    )
                    self.perimeter_points = []
                    self.drawing_perimeter = False
                elif self.drawing_perimeter:
                    print("Need at least 3 points to complete perimeter")

        elif flags == cv2.EVENT_FLAG_LBUTTON:  # Mouse is being dragged
            if self.mode == "MANUAL_GOOD":
                cv2.circle(self.manual_good_mask, (x, y), MANUAL_BRUSH_SIZE, 255, -1)
            elif self.mode == "MANUAL_BAD":
                cv2.circle(self.manual_bad_mask, (x, y), MANUAL_BRUSH_SIZE, 255, -1)

    def set_threshold(self, val):
        """Callback for the threshold trackbar."""
        self.threshold_value = val

    def set_gradient_kernel_size(self, val):
        """Callback for gradient kernel size trackbar."""
        self.gradient_kernel_size = max(10, val)  # Minimum size of 10

    def set_gradient_correction_strength(self, val):
        """Callback for gradient correction strength trackbar."""
        self.gradient_correction_strength = val / 100.0  # Convert to 0.0-1.0 range

    def create_trackbars(self):
        """Create all trackbars for parameter adjustment."""
        # Basic threshold
        cv2.createTrackbar(
            "Threshold", self.window_name, self.threshold_value, 255, self.set_threshold
        )

        # Gradient correction parameters
        cv2.createTrackbar(
            "Gradient Kernel",
            self.window_name,
            self.gradient_kernel_size,
            200,
            self.set_gradient_kernel_size,
        )
        cv2.createTrackbar(
            "Correction Strength",
            self.window_name,
            int(self.gradient_correction_strength * 100),
            100,
            self.set_gradient_correction_strength,
        )

    def process_and_display(self):
        """The main display loop, updates the image based on the current state."""
        display_image = self.image.copy()

        # --- Draw ROI points as they are being selected ---
        if self.roi_points:
            for i in range(len(self.roi_points)):
                cv2.circle(
                    display_image, self.roi_points[i], 4, (0, 255, 255), -1
                )  # Yellow dots
                if i > 0:
                    cv2.line(
                        display_image,
                        self.roi_points[i - 1],
                        self.roi_points[i],
                        (0, 255, 255),
                        2,
                    )
            if self.mode != "ROI_SELECT" and len(self.roi_points) > 2:
                # Draw the closed polygon after confirmation
                cv2.polylines(
                    display_image,
                    [np.array(self.roi_points)],
                    isClosed=True,
                    color=(0, 255, 255),
                    thickness=2,
                )

        # --- Draw perimeter points during perimeter drawing ---
        if self.drawing_perimeter and self.perimeter_points:
            color = (0, 255, 0) if self.mode == "PERIMETER_GOOD" else (0, 0, 255)
            for i in range(len(self.perimeter_points)):
                cv2.circle(display_image, self.perimeter_points[i], 3, color, -1)
                if i > 0:
                    cv2.line(
                        display_image,
                        self.perimeter_points[i - 1],
                        self.perimeter_points[i],
                        color,
                        2,
                    )

        # --- Process and overlay segmentation if ROI is defined ---
        if self.roi_mask is not None:
            # 1. Choose segmentation method
            if self.use_advanced_segmentation:
                auto_good_mask, corrected_image = self.gradient_corrected_threshold(
                    self.roi_mask
                )
            else:
                # Simple thresholding
                thresh_type = (
                    cv2.THRESH_BINARY if self.invert_logic else cv2.THRESH_BINARY_INV
                )
                _, auto_good_mask = cv2.threshold(
                    self.gray_image, self.threshold_value, 255, thresh_type
                )
                corrected_image = None

            # Show gradient-corrected image if requested
            if self.show_corrected_image and corrected_image is not None:
                # Convert single channel to 3-channel for display
                corrected_display = cv2.cvtColor(corrected_image, cv2.COLOR_GRAY2BGR)
                display_image = corrected_display

            # 2. Apply manual corrections
            # Start with the automatic mask
            final_good_mask = auto_good_mask
            # Force manually painted good areas to be white
            final_good_mask = cv2.bitwise_or(final_good_mask, self.manual_good_mask)
            # Force manually painted bad areas to be black
            final_good_mask = cv2.bitwise_and(
                final_good_mask, cv2.bitwise_not(self.manual_bad_mask)
            )

            # 3. Constrain everything to the ROI
            final_good_mask = cv2.bitwise_and(final_good_mask, self.roi_mask)

            # Apply overlays only if show_overlay is True
            if self.show_overlay:
                # Create overlays for visualization
                good_overlay = np.zeros_like(display_image)
                good_overlay[:] = (0, 255, 0)  # Green for good contact

                bad_overlay = np.zeros_like(display_image)
                bad_overlay[:] = (0, 0, 255)  # Red for bad contact

                # Find the bad contact area within the ROI
                roi_area_only = cv2.bitwise_not(
                    final_good_mask
                )  # Invert to get bad areas
                bad_mask_in_roi = cv2.bitwise_and(roi_area_only, self.roi_mask)

                # Apply overlays
                # Create masked overlays and blend them
                good_indices = final_good_mask > 0
                bad_indices = bad_mask_in_roi > 0

                # Apply green overlay for good contact areas
                display_image[good_indices] = cv2.addWeighted(
                    display_image[good_indices], 0.6, good_overlay[good_indices], 0.4, 0
                )

                # Apply red overlay for bad contact areas
                display_image[bad_indices] = cv2.addWeighted(
                    display_image[bad_indices], 0.6, bad_overlay[bad_indices], 0.4, 0
                )

        # --- Add instructions to the screen ---
        if self.show_help_text:
            self.draw_instructions(display_image)
        cv2.imshow(self.window_name, display_image)

    def draw_instructions(self, image):
        """Draws text instructions on the image."""
        y_pos = 20

        def put_text(text, color=(255, 255, 255)):
            nonlocal y_pos
            cv2.putText(
                image,
                text,
                (10, y_pos),
                cv2.FONT_HERSHEY_SIMPLEX,
                INSTRUCTION_FONT_SCALE,
                (0, 0, 0),
                INSTRUCTION_FONT_THICKNESS + 1,
                cv2.LINE_AA,
            )  # Shadow
            cv2.putText(
                image,
                text,
                (10, y_pos),
                cv2.FONT_HERSHEY_SIMPLEX,
                INSTRUCTION_FONT_SCALE,
                color,
                INSTRUCTION_FONT_THICKNESS,
                cv2.LINE_AA,
            )
            y_pos += 20

        if self.mode == "ROI_SELECT":
            put_text(f"MODE: Select ROI", (0, 255, 255))
            put_text("Left-click: Add point. Right-click: Remove last point.")
            put_text("Press 'c' to confirm ROI when done.")
        else:
            mode_color = (
                (255, 255, 0)
                if self.mode == "THRESHOLD"
                else (
                    (0, 255, 0)
                    if self.mode in ["MANUAL_GOOD", "PERIMETER_GOOD"]
                    else (0, 0, 255)
                )
            )
            put_text(f"MODE: {self.mode}", mode_color)

            # Show current segmentation method
            seg_method = (
                "Gradient-Corrected" if self.use_advanced_segmentation else "Simple"
            )
            put_text(f"Segmentation: {seg_method}", (255, 255, 0))
            put_text(f"Threshold: {self.threshold_value}", (255, 255, 0))
            if self.use_advanced_segmentation:
                put_text(f"Gradient Kernel: {self.gradient_kernel_size}", (255, 255, 0))
                put_text(
                    f"Correction: {self.gradient_correction_strength:.2f}",
                    (255, 255, 0),
                )

            put_text("--- Controls ---")
            put_text("'t': Adjust Threshold with slider")
            put_text("'a': Toggle Gradient-corrected/Simple threshold")
            put_text("'i': Invert good/bad regions")
            put_text("'o': Toggle overlay visibility")
            put_text("'v': Toggle gradient-corrected image view")
            put_text("'h': Toggle help text visibility")
            put_text("'g': Paint GOOD contact (hold left mouse)")
            put_text("'b': Paint BAD contact (hold left mouse)")
            put_text(
                "'p': Draw GOOD perimeter (left-click points, middle-click to fill)"
            )
            put_text(
                "'n': Draw BAD perimeter (left-click points, middle-click to fill)"
            )
            if self.drawing_perimeter:
                put_text("ESC to cancel perimeter", (255, 0, 255))
            put_text("'s': Calculate and show results")
            put_text("'r': Reset everything")
        put_text("'q': Quit")

    def run(self):
        """Main application loop."""
        print("--- Glue Contact Analyzer ---")
        print("Step 1: Define the ROI by clicking points on the image.")
        print("        Press 'c' to confirm the ROI and proceed.")

        while True:
            self.process_and_display()
            key = cv2.waitKey(20) & 0xFF

            if key == ord("q"):
                break

            elif key == ord("c") and self.mode == "ROI_SELECT":
                if len(self.roi_points) > 2:
                    print(
                        "\nStep 2: ROI Confirmed. Adjust threshold or perform manual corrections."
                    )
                    self.mode = "THRESHOLD"
                    self.roi_mask = np.zeros(self.image.shape[:2], dtype=np.uint8)
                    cv2.fillPoly(self.roi_mask, [np.array(self.roi_points)], 255)
                    self.create_trackbars()
                else:
                    print("Please select at least 3 points to form a polygon.")

            elif key == ord("t") and self.mode != "ROI_SELECT":
                self.mode = "THRESHOLD"
                print("Mode changed to THRESHOLD adjustment.")

            elif key == ord("g") and self.mode != "ROI_SELECT":
                self.mode = "MANUAL_GOOD"
                print("Mode changed to MANUAL GOOD. Hold and drag left mouse to paint.")

            elif key == ord("b") and self.mode != "ROI_SELECT":
                self.mode = "MANUAL_BAD"
                print("Mode changed to MANUAL BAD. Hold and drag left mouse to paint.")

            elif key == ord("p") and self.mode != "ROI_SELECT":
                self.mode = "PERIMETER_GOOD"
                self.perimeter_points = []
                self.drawing_perimeter = False
                print(
                    "Mode changed to PERIMETER GOOD. Left-click to add points, middle-click to fill perimeter."
                )

            elif key == ord("n") and self.mode != "ROI_SELECT":
                self.mode = "PERIMETER_BAD"
                self.perimeter_points = []
                self.drawing_perimeter = False
                print(
                    "Mode changed to PERIMETER BAD. Left-click to add points, middle-click to fill perimeter."
                )

            elif key == 27:  # ESC key
                if self.drawing_perimeter:
                    print("Cancelled perimeter drawing")
                    self.perimeter_points = []
                    self.drawing_perimeter = False

            elif key == ord("a") and self.mode != "ROI_SELECT":
                self.use_advanced_segmentation = not self.use_advanced_segmentation
                method = (
                    "Gradient-corrected threshold"
                    if self.use_advanced_segmentation
                    else "Simple threshold"
                )
                print(f"Switched to {method} segmentation.")

            elif key == ord("i") and self.mode != "ROI_SELECT":
                self.invert_good_bad_masks()

            elif key == ord("o") and self.mode != "ROI_SELECT":
                self.show_overlay = not self.show_overlay
                status = "ON" if self.show_overlay else "OFF"
                print(f"Overlay visibility: {status}")

            elif key == ord("v") and self.mode != "ROI_SELECT":
                self.show_corrected_image = not self.show_corrected_image
                status = "ON" if self.show_corrected_image else "OFF"
                print(f"Gradient-corrected image view: {status}")

            elif key == ord("h"):
                self.show_help_text = not self.show_help_text
                status = "ON" if self.show_help_text else "OFF"
                print(f"Help text visibility: {status}")

            elif key == ord("s") and self.roi_mask is not None:
                self.calculate_and_show_results()

            elif key == ord("r"):
                print("Resetting application state.")
                self.__init__(self.image_path)  # Re-initialize the object
                cv2.destroyWindow(self.window_name)
                self.run()  # Restart the run loop
                return  # Exit the current loop

        cv2.destroyAllWindows()

    def calculate_and_show_results(self):
        """Final calculation and printing of results."""
        # Recalculate the final mask to be sure it's up to date
        if self.use_advanced_segmentation:
            auto_good_mask, _ = self.gradient_corrected_threshold(self.roi_mask)
        else:
            thresh_type = (
                cv2.THRESH_BINARY if self.invert_logic else cv2.THRESH_BINARY_INV
            )
            _, auto_good_mask = cv2.threshold(
                self.gray_image, self.threshold_value, 255, thresh_type
            )

        final_good_mask = cv2.bitwise_or(auto_good_mask, self.manual_good_mask)
        final_good_mask = cv2.bitwise_and(
            final_good_mask, cv2.bitwise_not(self.manual_bad_mask)
        )
        final_good_mask = cv2.bitwise_and(final_good_mask, self.roi_mask)

        total_roi_pixels = cv2.countNonZero(self.roi_mask)
        if total_roi_pixels == 0:
            print("ROI has zero area. Cannot calculate.")
            return

        good_contact_pixels = cv2.countNonZero(final_good_mask)
        bad_contact_pixels = total_roi_pixels - good_contact_pixels

        good_percentage = (good_contact_pixels / total_roi_pixels) * 100
        bad_percentage = (bad_contact_pixels / total_roi_pixels) * 100

        print("\n--- Analysis Results ---")
        print(f"Total Pixels in ROI: {total_roi_pixels}")
        print(f"Good Contact Pixels:   {good_contact_pixels}")
        print(f"Bad Contact Pixels:    {bad_contact_pixels}")
        print("--------------------------")
        print(f"Good Contact: {good_percentage:.2f}%")
        print(f"Bad Contact:  {bad_percentage:.2f}%")
        print("--------------------------\n")

        # Display results on a new image
        result_img = np.zeros((200, 500, 3), dtype=np.uint8)
        cv2.putText(
            result_img,
            "Analysis Results",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (255, 255, 0),
            2,
        )
        cv2.putText(
            result_img,
            f"Good Contact: {good_percentage:.2f}%",
            (10, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
        )
        cv2.putText(
            result_img,
            f"Bad Contact:  {bad_percentage:.2f}%",
            (10, 120),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
        )
        cv2.putText(
            result_img,
            "Press any key to close.",
            (10, 180),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            1,
        )
        cv2.imshow("Results", result_img)
        cv2.waitKey(0)
        cv2.destroyWindow("Results")

    def gradient_corrected_threshold(self, roi_mask):
        """
        Apply local gradient correction to handle lighting variations, then threshold.
        Returns a tuple: (mask, corrected_image) where good contact areas are white (255) in mask.
        """
        # Apply gradient correction to the ENTIRE image first, not just ROI
        # This avoids boundary artifacts and gets better lighting estimation

        # Estimate local background using morphological opening with a large kernel
        kernel_size = self.gradient_kernel_size
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)
        )

        # Estimate background (local lighting) on the full image
        background = cv2.morphologyEx(self.gray_image, cv2.MORPH_OPEN, kernel)

        # Alternative: use Gaussian blur for smoother background estimation
        blur_size = kernel_size // 2 * 2 + 1  # Ensure odd number
        background_smooth = cv2.GaussianBlur(self.gray_image, (blur_size, blur_size), 0)

        # Blend the two background estimates
        background_final = cv2.addWeighted(background, 0.5, background_smooth, 0.5, 0)

        # Apply gradient correction to the full image
        if self.gradient_correction_strength > 0:
            # Subtract background to remove lighting gradients
            corrected = cv2.subtract(self.gray_image, background_final)

            # Add back a uniform level to maintain good contrast
            # Use mean of entire image for better global balance
            mean_background = cv2.mean(background_final)[0]
            corrected = cv2.add(corrected, int(mean_background))

            # Blend original and corrected based on correction strength
            corrected_final = cv2.addWeighted(
                self.gray_image,
                1.0 - self.gradient_correction_strength,
                corrected,
                self.gradient_correction_strength,
                0,
            )
        else:
            corrected_final = self.gray_image

        # Now apply ROI mask to the corrected image
        roi_corrected = cv2.bitwise_and(corrected_final, roi_mask)

        # Apply threshold to the corrected image
        thresh_type = cv2.THRESH_BINARY if self.invert_logic else cv2.THRESH_BINARY_INV
        _, thresholded = cv2.threshold(
            corrected_final, self.threshold_value, 255, thresh_type
        )

        # Apply ROI constraint to the final mask
        final_mask = cv2.bitwise_and(thresholded, roi_mask)

        return final_mask, corrected_final

    def invert_good_bad_masks(self):
        """Swap the good and bad manual masks and invert the segmentation logic."""
        # Swap manual masks
        temp_mask = self.manual_good_mask.copy()
        self.manual_good_mask = self.manual_bad_mask.copy()
        self.manual_bad_mask = temp_mask

        # Invert the automatic segmentation logic
        self.invert_logic = not self.invert_logic

        logic_state = "INVERTED" if self.invert_logic else "NORMAL"
        print(f"Inverted good and bad regions. Segmentation logic: {logic_state}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Interactively analyze glue contact area in an image."
    )
    parser.add_argument("image_path", help="Path to the input image file.")
    args = parser.parse_args()

    analyzer = GlueContactAnalyzer(args.image_path)
    analyzer.run()
