namespace N
{
    class C
    {
        int A()
        {
            return this.B();
        }

        int B()
        {
            Console.WriteLine("x");
            return 1;
        }
    }
}
