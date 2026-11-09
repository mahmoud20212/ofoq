<?php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Support\Str;

use App\Models\Product;

class ProductsController extends Controller
{
    public function index()
    {
        $products = Product::orderBy('created_at', 'desc')->get();

        return view('products.index', compact('products'));
    }

    public function create()
    {
        return view('products.create');
    }

    public function store(Request $request)
    {
        // التحقق من صحة البيانات المدخلة
        $request->validate([
            'name' => 'required',
            'category' => 'nullable|string|max:100',  // ✅ جديد
            'description' => 'required',
            'quantity' => 'required',
            'location' => 'required',
            'whatsapp' => ['required', 'regex:/^[0-9\s\-\+]+$/'],
            'image_path' => 'required|image|mimes:jpeg,png,jpg,gif|max:2048',
        ], [
            'whatsapp.regex' => 'يرجى إدخال رقم واتساب صالح .',
            'image_path.required' => 'يجب رفع صورة للكتاب.',
            'image_path.image' => 'الملف يجب أن يكون صورة.',
            'image_path.mimes' => 'الملف يجب أن يكون من نوع: jpeg, png, jpg, gif.',
            'image_path.max' => 'حجم الصورة يجب أن لا يتجاوز 2 ميجابايت.',
        ]);

        // إنشاء slug فريد
        $slug = Str::slug($request->name, '-') . '-' . uniqid();

        // ✅ معالجة الصورة مع default قيمة (حماية من undefined)
        $newImageName = null;
        if ($request->hasFile('image_path')) {
            $newImageName = uniqid() . '-' . $slug . '.' . $request->image_path->extension();
            $request->image_path->move(public_path('images'), $newImageName);
        }

        // إنشاء المنتج
        Product::create([
            'name' => $request->input('name'),
            'slug' => $slug,
            'category' => $request->input('category', 'عام'),  // ✅ من الفورم
            'description' => $request->input('description'),
            'quantity' => $request->input('quantity'),
            'location' => $request->input('location'),
            'whatsapp' => $request->input('whatsapp'),
            'image_path' => $newImageName,
            'user_id' => auth()->user()->id
        ]);

        return redirect('/products')->with('message', 'تم إضافة الكتاب بنجاح!');
    }


    public function show($slug)
    {
        $product = Product::where('slug', $slug)->first();

        // ✅ حماية: لو المنتج مش موجود، صفحة 404 نظيفة بدل 500
        if (!$product) {
            abort(404);
        }

        return view('products.show')->with('product', $product);
    }

    public function edit($slug)
    {
        $product = Product::where('slug', $slug)->firstOrFail();

        // ✅ Ownership check — مالك الكتاب أو أدمن
        if (auth()->id() !== $product->user_id && !auth()->user()->is_admin) {
            abort(403, 'ليس لديك صلاحية لتعديل هذا الكتاب');
        }

        return view('products.edit')->with('product', $product);
    }

    public function update(Request $request, $slug)
    {
        // جلب المنتج
        $product = Product::where('slug', $slug)->firstOrFail();

        // ✅ Ownership check — مالك الكتاب أو أدمن
        if (auth()->id() !== $product->user_id && !auth()->user()->is_admin) {
            abort(403, 'ليس لديك صلاحية لتعديل هذا الكتاب');
        }

        // التحقق من صحة البيانات المدخلة
        $validated = $request->validate([
            'name' => 'required|string|max:255',
            'category' => 'nullable|string|max:100',  // ✅ جديد
            'description' => 'required|string',
            'quantity' => 'required|integer|min:1',
            'location' => 'required|string|max:255',
            'whatsapp' => ['required', 'regex:/^[0-9\s\-\+]+$/'],
            'image_path' => 'nullable|image|mimes:jpeg,png,jpg,gif|max:2048',
        ], [
            'whatsapp.regex' => 'يرجى إدخال رقم واتساب صالح .',
        ]);

        // الاحتفاظ باسم الصورة القديمة
        $newImageName = $product->image_path;

        // التحقق مما إذا كان هناك صورة جديدة مرفوعة
        if ($request->hasFile('image_path')) {
            // حذف الصورة القديمة إذا وجدت
            if ($product->image_path) {
                $oldImagePath = public_path('images/' . $product->image_path);
                if (file_exists($oldImagePath)) {
                    unlink($oldImagePath);
                }
            }

            // رفع الصورة الجديدة
            $newImageName = uniqid() . '-' . Str::slug($request->name, '-') . '.' . $request->image_path->extension();
            $request->image_path->move(public_path('images'), $newImageName);
        }

        // ✅ slug فريد: نضيف ID المنتج عشان ما يتعارضش مع منتج تاني بنفس الاسم
        $newSlug = Str::slug($request->input('name'), '-') . '-' . $product->id;

        // تحديث بيانات المنتج
        $updated = $product->update([
            'name' => $request->input('name'),
            'slug' => $newSlug,  // ✅ فريد
            'category' => $request->input('category', $product->category),  // ✅ من الفورم
            'description' => $request->input('description'),
            'quantity' => $request->input('quantity'),
            'location' => $request->input('location'),
            'whatsapp' => $request->input('whatsapp'),
            'image_path' => $newImageName,
        ]);

        if (!$updated) {
            return redirect()->back()->with('error', 'حدث خطأ أثناء تحديث الكتاب');
        }

        return redirect()->route('products.show', $product->slug)->with('message', 'تم تعديل الكتاب بنجاح');
    }

    public function destroy($slug)
    {
        $product = Product::where('slug', $slug)->firstOrFail();

        // ✅ Ownership check — مالك الكتاب أو أدمن
        if (auth()->id() !== $product->user_id && !auth()->user()->is_admin) {
            abort(403, 'ليس لديك صلاحية لحذف هذا الكتاب');
        }

        $product->delete();

        return redirect('/products')->with('message', 'تم حذف الكتاب');
    }

    public function showUserData()
    {
        $user = auth()->user();
        $products = $user->products;
        $emergencyRequests = $user->emergencyRequests;

        return view('user.myProducts', compact('products', 'emergencyRequests'));
    }
}